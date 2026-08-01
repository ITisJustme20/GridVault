"""Project Vault routes and validation."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from ..extensions import db
from ..models import (
    PROJECT_STATUSES,
    Project,
    ProjectActivity,
    ProjectComment,
    ProjectObjective,
    User,
)


projects_bp = Blueprint("projects", __name__)

EDITABLE_STATUSES = tuple(
    status for status in PROJECT_STATUSES if status != "Archived"
)
CODENAME_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,39}$")
HTML_PATTERN = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")


def _contains_html(value: str) -> bool:
    return bool(HTML_PATTERN.search(value))


def _load_operators() -> list[User]:
    return db.session.execute(
        db.select(User).order_by(db.func.lower(User.username))
    ).scalars().all()


def _validate_assignees(raw_ids: list[str]) -> tuple[list[User], list[str]]:
    errors = []
    operator_ids = set()
    for raw_id in raw_ids:
        try:
            operator_ids.add(int(raw_id))
        except (TypeError, ValueError):
            errors.append("Assigned operators must be valid GridVault accounts.")
            return [], errors

    if not operator_ids:
        return [], errors

    operators = db.session.execute(
        db.select(User).where(User.id.in_(operator_ids))
    ).scalars().all()
    if len(operators) != len(operator_ids):
        errors.append("One or more assigned operators no longer exist.")
    return operators, errors


def _validate_project_form(project: Project | None = None):
    codename = request.form.get("codename", "").strip().upper()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    status = request.form.get("status", "").strip()
    objectives = [
        line.strip()
        for line in request.form.get("objectives", "").splitlines()
        if line.strip()
    ]
    operators, errors = _validate_assignees(
        request.form.getlist("assignee_ids")
    )

    if not CODENAME_PATTERN.fullmatch(codename):
        errors.append(
            "Codename must be 3–40 letters, numbers, underscores, or hyphens."
        )
    else:
        existing = db.session.execute(
            db.select(Project).where(
                db.func.lower(Project.codename) == codename.lower()
            )
        ).scalar_one_or_none()
        if existing is not None and (project is None or existing.id != project.id):
            errors.append("That project codename is already in use.")

    if not 3 <= len(title) <= 120:
        errors.append("Project title must contain 3–120 characters.")
    if _contains_html(title):
        errors.append("HTML markup is not allowed in project titles.")

    if not 10 <= len(description) <= 2000:
        errors.append("Description must contain 10–2,000 characters.")
    if _contains_html(description):
        errors.append("HTML markup is not allowed in project descriptions.")

    if status not in EDITABLE_STATUSES:
        errors.append("Select a valid project status.")

    if not objectives:
        errors.append("Add at least one project objective.")
    elif len(objectives) > 20:
        errors.append("Projects may contain at most 20 objectives.")
    for objective in objectives:
        if not 3 <= len(objective) <= 300:
            errors.append("Each objective must contain 3–300 characters.")
            break
        if _contains_html(objective):
            errors.append("HTML markup is not allowed in objectives.")
            break

    data = {
        "codename": codename,
        "title": title,
        "description": description,
        "status": status,
        "objectives": objectives,
        "operators": operators,
    }
    return data, errors


def _record_activity(
    project: Project,
    action: str,
    detail: str,
) -> None:
    project.activities.append(
        ProjectActivity(
            actor=current_user,
            action=action,
            detail=detail,
        )
    )


def _require_creator(project: Project) -> None:
    if project.creator_id != current_user.id:
        abort(403)


@projects_bp.get("/project-vault")
@login_required
def index():
    search_query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()

    if len(search_query) > 100:
        abort(400)
    if status_filter and status_filter not in PROJECT_STATUSES:
        abort(400)

    statement = db.select(Project)
    if status_filter:
        statement = statement.where(Project.status == status_filter)
    else:
        statement = statement.where(Project.status != "Archived")

    if search_query:
        search_term = f"%{search_query.lower()}%"
        statement = statement.where(
            or_(
                db.func.lower(Project.codename).like(search_term),
                db.func.lower(Project.title).like(search_term),
                db.func.lower(Project.description).like(search_term),
            )
        )

    projects = db.session.execute(
        statement.order_by(Project.updated_at.desc(), Project.id.desc())
    ).scalars().all()
    status_counts = dict(
        db.session.execute(
            db.select(Project.status, db.func.count(Project.id)).group_by(
                Project.status
            )
        ).all()
    )

    return render_template(
        "projects/index.html",
        projects=projects,
        project_statuses=PROJECT_STATUSES,
        search_query=search_query,
        status_filter=status_filter,
        status_counts=status_counts,
    )


@projects_bp.route("/project-vault/new", methods=["GET", "POST"])
@login_required
def create():
    operators = _load_operators()
    if request.method == "POST":
        data, errors = _validate_project_form()
        if not errors:
            project = Project(
                codename=data["codename"],
                title=data["title"],
                description=data["description"],
                status=data["status"],
                creator=current_user,
                assigned_operators=data["operators"],
            )
            project.objectives = [
                ProjectObjective(body=body, position=index)
                for index, body in enumerate(data["objectives"])
            ]
            _record_activity(
                project,
                "created",
                f"Created project {project.codename}.",
            )
            db.session.add(project)
            db.session.commit()
            flash(f"Project {project.codename} created.", "success")
            return redirect(url_for("projects.detail", project_id=project.id))

        for error in errors:
            flash(error, "error")

    return render_template(
        "projects/form.html",
        project=None,
        operators=operators,
        editable_statuses=EDITABLE_STATUSES,
        selected_operator_ids={
            int(value)
            for value in request.form.getlist("assignee_ids")
            if value.isdigit()
        },
        objectives_text=request.form.get("objectives", ""),
    )


@projects_bp.get("/project-vault/<int:project_id>")
@login_required
def detail(project_id):
    project = db.get_or_404(Project, project_id)
    activities = db.session.execute(
        db.select(ProjectActivity)
        .where(ProjectActivity.project_id == project.id)
        .order_by(ProjectActivity.created_at.desc(), ProjectActivity.id.desc())
    ).scalars().all()
    comments = db.session.execute(
        db.select(ProjectComment)
        .where(ProjectComment.project_id == project.id)
        .order_by(ProjectComment.created_at.asc(), ProjectComment.id.asc())
    ).scalars().all()
    return render_template(
        "projects/detail.html",
        project=project,
        activities=activities,
        comments=comments,
    )


@projects_bp.route("/project-vault/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit(project_id):
    project = db.get_or_404(Project, project_id)
    _require_creator(project)
    if project.status == "Archived":
        abort(409)

    operators = _load_operators()
    if request.method == "POST":
        data, errors = _validate_project_form(project)
        if not errors:
            changed_fields = []
            for field in ("codename", "title", "description", "status"):
                if getattr(project, field) != data[field]:
                    changed_fields.append(field)
                    setattr(project, field, data[field])

            current_assignees = {user.id for user in project.assigned_operators}
            new_assignees = {user.id for user in data["operators"]}
            if current_assignees != new_assignees:
                changed_fields.append("assignments")
                project.assigned_operators = data["operators"]

            current_objectives = [objective.body for objective in project.objectives]
            if current_objectives != data["objectives"]:
                changed_fields.append("objectives")
                project.objectives = [
                    ProjectObjective(body=body, position=index)
                    for index, body in enumerate(data["objectives"])
                ]

            if changed_fields:
                project.updated_at = datetime.now(timezone.utc)
                _record_activity(
                    project,
                    "updated",
                    "Updated " + ", ".join(changed_fields) + ".",
                )
                db.session.commit()
                flash(f"Project {project.codename} updated.", "success")
            else:
                flash("No project changes were detected.", "warning")
            return redirect(url_for("projects.detail", project_id=project.id))

        for error in errors:
            flash(error, "error")

    selected_operator_ids = (
        {
            int(value)
            for value in request.form.getlist("assignee_ids")
            if value.isdigit()
        }
        if request.method == "POST"
        else {user.id for user in project.assigned_operators}
    )
    objectives_text = (
        request.form.get("objectives", "")
        if request.method == "POST"
        else "\n".join(objective.body for objective in project.objectives)
    )
    return render_template(
        "projects/form.html",
        project=project,
        operators=operators,
        editable_statuses=EDITABLE_STATUSES,
        selected_operator_ids=selected_operator_ids,
        objectives_text=objectives_text,
    )


@projects_bp.post("/project-vault/<int:project_id>/archive")
@login_required
def archive(project_id):
    project = db.get_or_404(Project, project_id)
    _require_creator(project)
    if project.status != "Complete":
        flash("Only completed projects may be archived.", "error")
        return redirect(url_for("projects.detail", project_id=project.id))

    project.status = "Archived"
    project.updated_at = datetime.now(timezone.utc)
    _record_activity(project, "archived", f"Archived project {project.codename}.")
    db.session.commit()
    flash(f"Project {project.codename} archived.", "success")
    return redirect(url_for("projects.detail", project_id=project.id))


@projects_bp.post("/project-vault/<int:project_id>/discussion")
@login_required
def add_comment(project_id):
    project = db.get_or_404(Project, project_id)
    if project.status == "Archived":
        abort(409)
    body = request.form.get("body", "").strip()

    if not 1 <= len(body) <= 1000:
        flash("Discussion messages must contain 1–1,000 characters.", "error")
        return redirect(url_for("projects.detail", project_id=project.id))
    if _contains_html(body):
        flash("HTML markup is not allowed in project discussion.", "error")
        return redirect(url_for("projects.detail", project_id=project.id))

    project.comments.append(ProjectComment(author=current_user, body=body))
    project.updated_at = datetime.now(timezone.utc)
    _record_activity(
        project,
        "discussion",
        "Posted a project discussion message.",
    )
    db.session.commit()
    return redirect(url_for("projects.detail", project_id=project.id))
