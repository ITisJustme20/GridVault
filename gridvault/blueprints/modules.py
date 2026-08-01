"""Foundation routes for upcoming Mission Console modules."""

from flask import Blueprint, abort, render_template
from flask_login import login_required


modules_bp = Blueprint("modules", __name__)


MODULES = {
    "design-lab": {
        "title": "Design Lab",
        "code": "DL-02",
        "eyebrow": "Creative systems",
        "description": "Shape visual concepts, interface systems, and mission-ready assets in a focused creative workspace.",
        "capabilities": ["Creative briefs", "Asset boards", "Review checkpoints"],
    },
    "engineering-bay": {
        "title": "Engineering Bay",
        "code": "EB-03",
        "eyebrow": "Build operations",
        "description": "Coordinate technical work, system health, and implementation milestones across active missions.",
        "capabilities": ["Build queues", "System telemetry", "Technical handoffs"],
    },
    "briefing-room": {
        "title": "Briefing Room",
        "code": "BR-05",
        "eyebrow": "Decision support",
        "description": "Prepare objectives, surface context, and capture decisions before the team moves into action.",
        "capabilities": ["Mission briefs", "Decision logs", "Action registers"],
    },
    "archive": {
        "title": "Archive",
        "code": "AR-06",
        "eyebrow": "Operational memory",
        "description": "Retrieve completed missions and historical context without cluttering current operations.",
        "capabilities": ["Historical search", "Mission timelines", "Retention controls"],
    },
    "settings": {
        "title": "Settings",
        "code": "ST-07",
        "eyebrow": "Console controls",
        "description": "Manage operator preferences, security posture, and workspace behavior from a single control surface.",
        "capabilities": ["Profile controls", "Notification rules", "Security preferences"],
    },
}


@modules_bp.get("/<module_slug>")
@login_required
def placeholder(module_slug):
    module = MODULES.get(module_slug)
    if module is None:
        abort(404)
    return render_template(
        "modules/placeholder.html",
        module=module,
        module_slug=module_slug,
    )
