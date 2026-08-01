"""Design Lab gallery, dossiers, concept boards, and review workflow."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_

from ..extensions import db
from ..models import (
    DESIGN_STAGES,
    Design,
    DesignActivity,
    DesignAsset,
    DesignRevision,
    DesignReviewComment,
    DesignStatusHistory,
    Project,
    User,
)


design_lab_bp = Blueprint("design_lab", __name__)
CODENAME_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,39}$")
HTML_PATTERN = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
ELEMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
EDITABLE_STAGES = ("Concept", "Exploring")
BOARD_TYPES = {
    "text",
    "heading",
    "image",
    "rectangle",
    "circle",
    "arrow",
    "label",
    "swatch",
    "reference",
}
DOSSIER_FIELDS = (
    "problem",
    "proposed_solution",
    "intended_user",
    "design_goals",
    "constraints",
    "materials",
    "dimensions",
    "components",
    "risks",
    "references",
)
FIELD_RULES = {
    "problem": (10, 3000, "Problem"),
    "proposed_solution": (10, 3000, "Proposed solution"),
    "intended_user": (3, 300, "Intended user"),
    "design_goals": (3, 2000, "Design goals"),
    "constraints": (0, 2000, "Constraints"),
    "materials": (0, 2000, "Materials"),
    "dimensions": (0, 500, "Dimensions"),
    "components": (0, 2000, "Components"),
    "risks": (0, 2000, "Risks"),
    "references": (0, 2000, "References"),
}


def _contains_html(value: str) -> bool:
    return bool(HTML_PATTERN.search(value))


def _available_projects():
    return db.session.execute(
        db.select(Project)
        .where(Project.status != "Archived")
        .order_by(Project.codename)
    ).scalars().all()


def _operators():
    return db.session.execute(
        db.select(User).order_by(db.func.lower(User.username))
    ).scalars().all()


def _is_collaborator(design: Design) -> bool:
    return any(operator.id == current_user.id for operator in design.collaborators)


def _is_team_member(design: Design) -> bool:
    return design.creator_id == current_user.id or _is_collaborator(design)


def _require_team_member(design: Design) -> None:
    if not _is_team_member(design):
        abort(403)


def _require_creator(design: Design) -> None:
    if design.creator_id != current_user.id:
        abort(403)


def _require_mutable(design: Design) -> None:
    if design.stage == "Archived":
        abort(409)
    if design.stage == "In Review":
        abort(409, "A design under review cannot be edited.")


def _validate_collaborators(raw_ids: list[str], creator_id=None):
    errors = []
    ids = set()
    for raw_id in raw_ids:
        if not raw_id.isdigit():
            return [], ["Collaborators must be valid GridVault operators."]
        ids.add(int(raw_id))
    if creator_id in ids:
        ids.remove(creator_id)
    if not ids:
        return [], errors
    users = db.session.execute(db.select(User).where(User.id.in_(ids))).scalars().all()
    if len(users) != len(ids):
        errors.append("One or more collaborators no longer exist.")
    return users, errors


def _valid_reference_lines(value: str) -> bool:
    for line in value.splitlines():
        for token in line.split():
            if token.lower().startswith(("http://", "https://")):
                parsed = urlparse(token.rstrip(".,;)"))
                if parsed.scheme != "https" or not parsed.netloc:
                    return False
    return True


def _validate_form(design=None, manage_collaborators=True):
    codename = request.form.get("codename", "").strip().upper()
    title = request.form.get("title", "").strip()
    stage = request.form.get("stage", "Concept").strip()
    project_id = request.form.get("project_id", "").strip()
    values = {field: request.form.get(field, "").strip() for field in DOSSIER_FIELDS}
    errors = []

    if not CODENAME_PATTERN.fullmatch(codename):
        errors.append("Codename must be 3–40 letters, numbers, underscores, or hyphens.")
    else:
        existing = db.session.execute(
            db.select(Design).where(db.func.lower(Design.codename) == codename.lower())
        ).scalar_one_or_none()
        if existing is not None and (design is None or existing.id != design.id):
            errors.append("That design codename is already in use.")
    if not 3 <= len(title) <= 120:
        errors.append("Title must contain 3–120 characters.")
    if _contains_html(title):
        errors.append("HTML markup is not allowed in titles.")
    if stage not in EDITABLE_STAGES:
        errors.append("Select a valid editable design stage.")

    for field, value in values.items():
        minimum, maximum, label = FIELD_RULES[field]
        if not minimum <= len(value) <= maximum:
            errors.append(f"{label} must contain {minimum}–{maximum} characters.")
        if _contains_html(value):
            errors.append(f"HTML markup is not allowed in {label.lower()}.")
    if values["references"] and not _valid_reference_lines(values["references"]):
        errors.append("Reference URLs must use a valid HTTPS address.")

    project = None
    if project_id:
        project = db.session.get(Project, int(project_id)) if project_id.isdigit() else None
        if project is None or project.status == "Archived":
            errors.append("Select an available Project Vault project.")

    if manage_collaborators:
        collaborators, collaborator_errors = _validate_collaborators(
            request.form.getlist("collaborator_ids"),
            current_user.id,
        )
        errors.extend(collaborator_errors)
    else:
        collaborators = list(design.collaborators)

    data = {
        "codename": codename,
        "title": title,
        "stage": stage,
        "project": project,
        "collaborators": collaborators,
        **values,
    }
    return data, errors


def _snapshot(design: Design) -> str:
    data = {
        "codename": design.codename,
        "title": design.title,
        "stage": design.stage,
        "project": design.project.codename if design.project else None,
        "creator": design.creator.username,
        "collaborators": [user.username for user in design.collaborators],
        "cover_filename": design.cover_filename,
        "board": json.loads(design.board_state or "[]"),
    }
    data.update({field: getattr(design, field) for field in DOSSIER_FIELDS})
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _add_revision(design: Design, note: str, *, initial=False) -> DesignRevision:
    if not initial:
        design.revision_number += 1
    revision = DesignRevision(
        design=design,
        revision_number=design.revision_number,
        snapshot=_snapshot(design),
        change_note=note,
        author=current_user,
    )
    db.session.add(revision)
    return revision


def _record_activity(design: Design, action: str, detail: str) -> None:
    db.session.add(
        DesignActivity(
            design=design,
            actor=current_user,
            action=action,
            detail=detail,
        )
    )


def _change_stage(design: Design, stage: str, note: str) -> None:
    previous = design.stage
    design.stage = stage
    db.session.add(
        DesignStatusHistory(
            design=design,
            actor=current_user,
            from_stage=previous,
            to_stage=stage,
            note=note,
        )
    )


def _validate_board(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        return None, "The concept board payload is invalid."
    elements = payload["elements"]
    if len(elements) > 250:
        return None, "A concept board may contain at most 250 elements."
    cleaned = []
    for item in elements:
        if not isinstance(item, dict) or item.get("type") not in BOARD_TYPES:
            return None, "The concept board contains an unsupported element."
        element_id = str(item.get("id", ""))
        if not ELEMENT_ID_PATTERN.fullmatch(element_id):
            return None, "A concept board element has an invalid identifier."
        try:
            x, y = float(item.get("x", 0)), float(item.get("y", 0))
            width, height = float(item.get("width", 160)), float(item.get("height", 100))
            z = int(item.get("z", 0))
        except (TypeError, ValueError):
            return None, "A concept board element has invalid geometry."
        if not (
            -10000 <= x <= 10000
            and -10000 <= y <= 10000
            and 20 <= width <= 4000
            and 20 <= height <= 4000
            and -1000 <= z <= 1000
        ):
            return None, "A concept board element is outside the allowed bounds."
        content = str(item.get("content", "")).strip()[:1001]
        if len(content) > 1000 or _contains_html(content):
            return None, "Board text must be plain text with at most 1,000 characters."
        color = str(item.get("color", "#67d8c4"))
        if not HEX_COLOR_PATTERN.fullmatch(color):
            return None, "Board colors must use six-digit hex values."
        url = str(item.get("url", "")).strip()
        if url:
            parsed = urlparse(url)
            if item["type"] == "image":
                prefix = f"/design-lab/{request.view_args['design_id']}/assets/"
                filename = url.removeprefix(prefix)
                asset_exists = filename and db.session.execute(
                    db.select(DesignAsset.id).where(
                        DesignAsset.design_id == request.view_args["design_id"],
                        DesignAsset.stored_filename == filename,
                    )
                ).scalar_one_or_none()
                if not url.startswith(prefix) or not asset_exists:
                    return None, "Board images must use an uploaded Design Lab asset."
            elif parsed.scheme != "https" or not parsed.netloc or len(url) > 500:
                return None, "Reference card URLs must use a valid HTTPS address."
        cleaned.append(
            {
                "id": element_id,
                "type": item["type"],
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "z": z,
                "content": content,
                "color": color,
                "url": url,
            }
        )
    return cleaned, None


def _detect_image(data: bytes):
    def safe_dimensions(width, height):
        return (
            0 < width <= 10000
            and 0 < height <= 10000
            and width * height <= 25_000_000
        )

    if (
        len(data) >= 24
        and data.startswith(b"\x89PNG\r\n\x1a\n")
        and data[12:16] == b"IHDR"
        and safe_dimensions(
            int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"),
        )
    ):
        return "png", "image/png"
    if len(data) >= 10 and data.startswith((b"GIF87a", b"GIF89a")):
        width = int.from_bytes(data[6:8], "little")
        height = int.from_bytes(data[8:10], "little")
        if safe_dimensions(width, height):
            return "gif", "image/gif"
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        subtype = data[12:16]
        width = height = 0
        if subtype == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
        elif subtype == b"VP8L" and data[20] == 0x2F:
            width = 1 + data[21] + ((data[22] & 0x3F) << 8)
            height = 1 + (data[22] >> 6) + (data[23] << 2) + ((data[24] & 0x0F) << 10)
        elif subtype == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
        if safe_dimensions(width, height):
            return "webp", "image/webp"
    if data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"):
        position = 2
        start_of_frame = {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        while position + 8 < len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            marker = data[position + 1]
            if marker in (0xD8, 0xD9):
                position += 2
                continue
            segment_length = int.from_bytes(data[position + 2:position + 4], "big")
            if segment_length < 2 or position + 2 + segment_length > len(data):
                break
            if marker in start_of_frame:
                height = int.from_bytes(data[position + 5:position + 7], "big")
                width = int.from_bytes(data[position + 7:position + 9], "big")
                if safe_dimensions(width, height):
                    return "jpg", "image/jpeg"
                break
            position += 2 + segment_length
    return None


@design_lab_bp.get("/design-lab")
@login_required
def index():
    search_query = request.args.get("q", "").strip()
    stage_filter = request.args.get("stage", "").strip()
    if len(search_query) > 100 or (stage_filter and stage_filter not in DESIGN_STAGES):
        abort(400)
    statement = db.select(Design)
    statement = (
        statement.where(Design.stage == stage_filter)
        if stage_filter
        else statement.where(Design.stage != "Archived")
    )
    if search_query:
        term = f"%{search_query.lower()}%"
        statement = statement.where(
            or_(
                db.func.lower(Design.codename).like(term),
                db.func.lower(Design.title).like(term),
                db.func.lower(Design.problem).like(term),
                db.func.lower(Design.proposed_solution).like(term),
            )
        )
    designs = db.session.execute(
        statement.order_by(Design.updated_at.desc(), Design.id.desc())
    ).scalars().all()
    counts = dict(
        db.session.execute(
            db.select(Design.stage, db.func.count(Design.id)).group_by(Design.stage)
        ).all()
    )
    return render_template(
        "design_lab/index.html",
        designs=designs,
        stages=DESIGN_STAGES,
        counts=counts,
        search_query=search_query,
        stage_filter=stage_filter,
    )


@design_lab_bp.route("/design-lab/new", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        data, errors = _validate_form()
        if not errors:
            collaborators = data.pop("collaborators")
            design = Design(**data, creator=current_user, collaborators=collaborators)
            db.session.add(design)
            db.session.flush()
            _add_revision(design, "Initial design dossier.", initial=True)
            db.session.add(
                DesignStatusHistory(
                    design=design,
                    actor=current_user,
                    from_stage=None,
                    to_stage=design.stage,
                    note="Design created.",
                )
            )
            _record_activity(design, "created", f"Created design {design.codename}.")
            db.session.commit()
            flash(f"Design {design.codename} created.", "success")
            return redirect(url_for("design_lab.detail", design_id=design.id))
        for error in errors:
            flash(error, "error")
    return render_template(
        "design_lab/form.html",
        design=None,
        projects=_available_projects(),
        operators=_operators(),
        editable_stages=EDITABLE_STAGES,
        selected_collaborators={
            int(value)
            for value in request.form.getlist("collaborator_ids")
            if value.isdigit()
        },
    )


@design_lab_bp.get("/design-lab/<int:design_id>")
@login_required
def detail(design_id):
    design = db.get_or_404(Design, design_id)
    comments = db.session.execute(
        db.select(DesignReviewComment)
        .where(DesignReviewComment.design_id == design.id)
        .order_by(DesignReviewComment.created_at, DesignReviewComment.id)
    ).scalars().all()
    revisions = db.session.execute(
        db.select(DesignRevision)
        .where(DesignRevision.design_id == design.id)
        .order_by(DesignRevision.revision_number.desc())
    ).scalars().all()
    history = db.session.execute(
        db.select(DesignStatusHistory)
        .where(DesignStatusHistory.design_id == design.id)
        .order_by(DesignStatusHistory.created_at.desc(), DesignStatusHistory.id.desc())
    ).scalars().all()
    return render_template(
        "design_lab/detail.html",
        design=design,
        comments=comments,
        revisions=revisions,
        history=history,
        is_team_member=_is_team_member(design),
        is_collaborator=_is_collaborator(design),
    )


@design_lab_bp.route("/design-lab/<int:design_id>/edit", methods=["GET", "POST"])
@login_required
def edit(design_id):
    design = db.get_or_404(Design, design_id)
    _require_team_member(design)
    _require_mutable(design)
    managing = design.creator_id == current_user.id
    if request.method == "POST":
        data, errors = _validate_form(design, manage_collaborators=managing)
        note = request.form.get("change_note", "").strip()
        if not 3 <= len(note) <= 500 or _contains_html(note):
            errors.append("Change notes must contain 3–500 plain-text characters.")
        if not errors:
            collaborators = data.pop("collaborators")
            changed = []
            requested_stage = data.pop("stage")
            for field, value in data.items():
                if getattr(design, field) != value:
                    setattr(design, field, value)
                    changed.append(field)
            if design.stage != requested_stage:
                _change_stage(design, requested_stage, note)
                changed.append("stage")
            current_collaborators = {
                user.id for user in design.collaborators
            }
            submitted_collaborators = {
                user.id for user in collaborators
            }
            if managing and current_collaborators != submitted_collaborators:
                design.collaborators = collaborators
                changed.append("collaborators")
            if changed:
                design.updated_at = datetime.now(timezone.utc)
                _add_revision(design, note)
                _record_activity(design, "revised", f"Created revision {design.revision_number}.")
                db.session.commit()
                flash(f"Revision {design.revision_number} saved.", "success")
            else:
                flash("No dossier changes were detected.", "warning")
            return redirect(url_for("design_lab.detail", design_id=design.id))
        for error in errors:
            flash(error, "error")
    selected = (
        {
            int(value)
            for value in request.form.getlist("collaborator_ids")
            if value.isdigit()
        }
        if request.method == "POST" and managing
        else {user.id for user in design.collaborators}
    )
    return render_template(
        "design_lab/form.html",
        design=design,
        projects=_available_projects(),
        operators=_operators(),
        editable_stages=EDITABLE_STAGES,
        selected_collaborators=selected,
        managing_collaborators=managing,
    )


@design_lab_bp.get("/design-lab/<int:design_id>/board")
@login_required
def board(design_id):
    design = db.get_or_404(Design, design_id)
    can_edit = _is_team_member(design) and design.stage not in (
        "Archived",
        "In Review",
    )
    return render_template(
        "design_lab/board.html",
        design=design,
        can_edit=can_edit,
    )


@design_lab_bp.post("/design-lab/<int:design_id>/board")
@login_required
def save_board(design_id):
    design = db.get_or_404(Design, design_id)
    _require_team_member(design)
    _require_mutable(design)
    elements, error = _validate_board(request.get_json(silent=True))
    if error:
        return jsonify({"ok": False, "error": error}), 400
    if design.stage in ("Approved", "Rejected"):
        _change_stage(design, "Exploring", "Concept board reopened after review.")
    design.board_state = json.dumps(elements, separators=(",", ":"))
    design.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"ok": True, "saved_at": design.updated_at.isoformat()})


@design_lab_bp.post("/design-lab/<int:design_id>/revisions")
@login_required
def create_revision(design_id):
    design = db.get_or_404(Design, design_id)
    _require_team_member(design)
    _require_mutable(design)
    note = request.form.get("change_note", "").strip()
    if not 3 <= len(note) <= 500 or _contains_html(note):
        flash("Change notes must contain 3–500 plain-text characters.", "error")
    else:
        if design.stage in ("Approved", "Rejected"):
            _change_stage(design, "Exploring", "New revision opened after review.")
        _add_revision(design, note)
        _record_activity(
            design,
            "revised",
            f"Created revision {design.revision_number} from the concept board.",
        )
        db.session.commit()
        flash(f"Revision {design.revision_number} captured.", "success")
    return redirect(url_for("design_lab.board", design_id=design.id))


@design_lab_bp.get("/design-lab/<int:design_id>/revisions/<int:revision_number>")
@login_required
def revision(design_id, revision_number):
    design = db.get_or_404(Design, design_id)
    record = db.session.execute(
        db.select(DesignRevision).where(
            DesignRevision.design_id == design.id,
            DesignRevision.revision_number == revision_number,
        )
    ).scalar_one_or_none()
    if record is None:
        abort(404)
    return render_template(
        "design_lab/revision.html",
        design=design,
        revision=record,
        snapshot=json.loads(record.snapshot),
    )


@design_lab_bp.post("/design-lab/<int:design_id>/submit-review")
@login_required
def submit_review(design_id):
    design = db.get_or_404(Design, design_id)
    _require_team_member(design)
    _require_mutable(design)
    note = request.form.get("change_note", "").strip()
    if not 3 <= len(note) <= 500 or _contains_html(note):
        flash("Review notes must contain 3–500 plain-text characters.", "error")
    elif not design.collaborators:
        flash("Assign at least one collaborator before requesting review.", "error")
    else:
        _change_stage(design, "In Review", note)
        _add_revision(design, note)
        _record_activity(
            design,
            "review",
            f"Submitted revision {design.revision_number} for review.",
        )
        db.session.commit()
        flash("Design submitted for collaborator review.", "success")
    return redirect(url_for("design_lab.detail", design_id=design.id))


@design_lab_bp.post("/design-lab/<int:design_id>/review")
@login_required
def review(design_id):
    design = db.get_or_404(Design, design_id)
    if not _is_collaborator(design):
        abort(403)
    if design.stage != "In Review":
        abort(409)
    decision = request.form.get("decision", "").strip()
    note = request.form.get("note", "").strip()
    if decision not in ("approve", "reject"):
        abort(400)
    if not 3 <= len(note) <= 500 or _contains_html(note):
        flash("Review decisions require a 3–500 character plain-text note.", "error")
    else:
        stage = "Approved" if decision == "approve" else "Rejected"
        _change_stage(design, stage, note)
        _add_revision(design, note)
        if stage == "Approved":
            design.published_revision_number = design.revision_number
        _record_activity(
            design,
            decision,
            f"{stage} revision {design.revision_number}.",
        )
        db.session.commit()
        flash(f"Design {stage.lower()}.", "success")
    return redirect(url_for("design_lab.detail", design_id=design.id))


@design_lab_bp.post("/design-lab/<int:design_id>/comments")
@login_required
def add_comment(design_id):
    design = db.get_or_404(Design, design_id)
    _require_team_member(design)
    if design.stage == "Archived":
        abort(409)
    body = request.form.get("body", "").strip()
    revision_number = request.form.get("revision_number", "").strip()
    exists = revision_number.isdigit() and db.session.execute(
        db.select(DesignRevision.id).where(
            DesignRevision.design_id == design.id,
            DesignRevision.revision_number == int(revision_number),
        )
    ).scalar_one_or_none()
    if not exists:
        abort(400)
    if not 1 <= len(body) <= 1000 or _contains_html(body):
        flash("Review comments must contain 1–1,000 plain-text characters.", "error")
    else:
        db.session.add(
            DesignReviewComment(
                design=design,
                author=current_user,
                revision_number=int(revision_number),
                body=body,
            )
        )
        _record_activity(
            design,
            "commented",
            f"Commented on revision {revision_number}.",
        )
        db.session.commit()
    return redirect(url_for("design_lab.detail", design_id=design.id))


@design_lab_bp.post("/design-lab/<int:design_id>/archive")
@login_required
def archive(design_id):
    design = db.get_or_404(Design, design_id)
    _require_creator(design)
    if design.stage != "Approved":
        flash("Only approved designs may be archived.", "error")
    else:
        _change_stage(design, "Archived", "Approved dossier archived.")
        _add_revision(design, "Archived approved design dossier.")
        _record_activity(
            design,
            "archived",
            f"Archived design {design.codename}.",
        )
        db.session.commit()
        flash(f"Design {design.codename} archived.", "success")
    return redirect(url_for("design_lab.detail", design_id=design.id))


@design_lab_bp.post("/design-lab/<int:design_id>/uploads")
@login_required
def upload(design_id):
    design = db.get_or_404(Design, design_id)
    _require_team_member(design)
    _require_mutable(design)
    uploaded = request.files.get("image")
    usage = request.form.get("usage", "board")
    if usage not in ("board", "cover"):
        return jsonify({"ok": False, "error": "Select a valid image usage."}), 400
    if uploaded is None or not uploaded.filename:
        return jsonify({"ok": False, "error": "Choose an image to upload."}), 400
    maximum = current_app.config["DESIGN_UPLOAD_MAX_BYTES"]
    data = uploaded.stream.read(maximum + 1)
    detected = _detect_image(data)
    if not data or len(data) > maximum or detected is None:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "Upload a PNG, JPEG, GIF, or WebP image no larger than 5 MB."
                ),
            }
        ), 400
    extension, mime_type = detected
    filename = f"{design.id}-{uuid.uuid4().hex}.{extension}"
    folder = Path(current_app.config["DESIGN_UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_bytes(data)
    asset = DesignAsset(
        design=design,
        uploader=current_user,
        original_filename=Path(uploaded.filename).name[:255],
        stored_filename=filename,
        mime_type=mime_type,
        byte_size=len(data),
    )
    db.session.add(asset)
    if usage == "cover":
        design.cover_filename = filename
    if design.stage in ("Approved", "Rejected"):
        _change_stage(design, "Exploring", "Visual assets reopened after review.")
    if usage == "cover":
        _add_revision(design, "Updated the design cover image.")
    design.updated_at = datetime.now(timezone.utc)
    detail = (
        "Updated the cover image."
        if usage == "cover"
        else "Uploaded a concept board image."
    )
    _record_activity(design, "uploaded", detail)
    db.session.commit()
    asset_url = url_for("design_lab.asset", design_id=design.id, filename=filename)
    wants_json = (
        request.accept_mimetypes.best == "application/json"
        or request.headers.get("X-Requested-With") == "fetch"
    )
    if wants_json:
        return jsonify({"ok": True, "url": asset_url})
    flash("Cover image updated.", "success")
    return redirect(url_for("design_lab.detail", design_id=design.id))


@design_lab_bp.get("/design-lab/<int:design_id>/assets/<path:filename>")
@login_required
def asset(design_id, filename):
    design = db.get_or_404(Design, design_id)
    allowed = design.cover_filename == filename or db.session.execute(
        db.select(DesignAsset.id).where(
            DesignAsset.design_id == design.id,
            DesignAsset.stored_filename == filename,
        )
    ).scalar_one_or_none()
    if not allowed:
        abort(404)
    return send_from_directory(current_app.config["DESIGN_UPLOAD_FOLDER"], filename)
