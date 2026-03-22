"""Shared helpers for After Effects tools."""


def ae_comp_selector(comp_name: str | None) -> str:
    """Generate JSX to select a comp by name, or use activeItem.

    Used by multiple AE feature modules to target a specific composition.
    """
    if not comp_name:
        return 'var comp = app.project.activeItem;'
    return f"""
var comp = null;
for (var i = 1; i <= app.project.numItems; i++) {{
    if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "{comp_name}") {{
        comp = app.project.item(i); break;
    }}
}}
"""
