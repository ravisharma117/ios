#!/usr/bin/env python3
"""Inspect the Xcode project in the current directory for the iOS build workflow.

Nothing is hardcoded: the workspace/project, the application scheme and the
place where Xcode expects GoogleService-Info.plist are all worked out from the
repository contents, so the workflow keeps working if files are renamed.

Inputs (environment, both optional):
  WORKSPACE_INPUT  explicit .xcworkspace / .xcodeproj path, overrides detection
  SCHEME_INPUT     explicit scheme name, overrides detection

Output: KEY=VALUE lines appended to $GITHUB_ENV (or printed when it is unset):
  BUILD_CONTAINER_FLAG  -workspace | -project
  BUILD_CONTAINER       path of the workspace / project to build
  SCHEME                scheme to build
  SCHEME_PROJECT        .xcodeproj that owns the scheme (used to list configurations)
  FIREBASE_PLIST_PATH   where the project expects GoogleService-Info.plist,
                        or empty if the project does not reference one

Everything else printed is for the build log. Errors are reported as GitHub
"::error::" annotations and the script exits non-zero.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

SKIP_DIRS = {"Pods", ".git", "DerivedData", "build", "node_modules"}
FIREBASE_PLIST = "GoogleService-Info.plist"


def fail(title, message):
    print(f"::error title={title}::{message}")
    sys.exit(1)


def find_bundles(suffix):
    """Find *suffix directories in the repo root and one level below, skipping Pods."""
    found = []
    for root, dirs, _ in os.walk("."):
        depth = 0 if root == "." else root.count(os.sep)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found += [os.path.normpath(os.path.join(root, d)) for d in dirs if d.endswith(suffix)]
        # Never descend into Xcode bundles (they hold nested project.xcworkspace files).
        dirs[:] = [d for d in dirs if not d.endswith((".xcodeproj", ".xcworkspace"))]
        if depth >= 1:
            dirs[:] = []
    return sorted(found)


def choose_container():
    explicit = os.environ.get("WORKSPACE_INPUT", "").strip()
    if explicit:
        if not os.path.isdir(explicit) or not explicit.rstrip("/").endswith((".xcworkspace", ".xcodeproj")):
            fail("Workspace not found", f"'{explicit}' is not an existing .xcworkspace or .xcodeproj.")
        path = explicit.rstrip("/")
        return ("-workspace" if path.endswith(".xcworkspace") else "-project"), path

    workspaces = find_bundles(".xcworkspace")
    if len(workspaces) == 1:
        return "-workspace", workspaces[0]
    if len(workspaces) > 1:
        fail("Several workspaces found",
             "Pick one with the 'workspace' input: " + ", ".join(workspaces))

    projects = find_bundles(".xcodeproj")
    if len(projects) == 1:
        return "-project", projects[0]
    if not projects:
        fail("No Xcode project found", "No .xcworkspace or .xcodeproj in the repository.")
    fail("Several projects found",
         "No workspace to tie them together; pick one with the 'workspace' input: " + ", ".join(projects))


def projects_of(flag, container):
    """The .xcodeproj directories that belong to the container, excluding Pods."""
    if flag == "-project":
        return [container]
    data = os.path.join(container, "contents.xcworkspacedata")
    refs = re.findall(r'location\s*=\s*"[a-z]+:([^"]+\.xcodeproj)"', open(data, encoding="utf-8").read())
    base = os.path.dirname(container) or "."
    projects = [os.path.normpath(os.path.join(base, r)) for r in refs]
    return [p for p in projects if "Pods" not in p.split(os.sep) and os.path.isdir(p)]


def shared_app_schemes(flag, container):
    """Shared schemes whose build action produces an .app: [(name, project)]."""
    owners = projects_of(flag, container)
    if flag == "-workspace":
        owners.append(container)
    schemes = []
    for owner in owners:
        scheme_dir = os.path.join(owner, "xcshareddata", "xcschemes")
        if not os.path.isdir(scheme_dir):
            continue
        for fname in sorted(os.listdir(scheme_dir)):
            if not fname.endswith(".xcscheme"):
                continue
            tree = ET.parse(os.path.join(scheme_dir, fname))
            names = [r.get("BuildableName", "") for r in tree.iterfind("./BuildAction//BuildableReference")]
            if any(n.endswith(".app") for n in names):
                project = owner if owner.endswith(".xcodeproj") else None
                if project is None:  # workspace-level scheme: use the project it points at
                    ref = tree.find("./BuildAction//BuildableReference")
                    target = ref.get("ReferencedContainer", "").split(":", 1)[-1]
                    project = os.path.normpath(os.path.join(os.path.dirname(container) or ".", target))
                schemes.append((fname[: -len(".xcscheme")], project))
    return schemes


def choose_scheme(flag, container):
    schemes = shared_app_schemes(flag, container)
    print("Shared application schemes: " + (", ".join(f"{n} ({p})" for n, p in schemes) or "none"))
    explicit = os.environ.get("SCHEME_INPUT", "").strip()
    if explicit:
        for name, project in schemes:
            if name == explicit:
                return name, project
        fail("Scheme not found",
             f"Scheme '{explicit}' is not a shared application scheme. Available: "
             + (", ".join(n for n, _ in schemes) or "none"))
    if len(schemes) == 1:
        return schemes[0]
    if not schemes:
        fail("No application scheme",
             "No shared scheme builds an .app. In Xcode: Product > Scheme > Manage Schemes > tick 'Shared', "
             "then commit the .xcscheme file.")
    stem = os.path.splitext(os.path.basename(container))[0]
    matching = [s for s in schemes if s[0] == stem]
    if len(matching) == 1:
        return matching[0]
    fail("Several application schemes",
         "Pick one with the 'scheme' input: " + ", ".join(n for n, _ in schemes))


def firebase_plist_path(project):
    """Where the project expects GoogleService-Info.plist, relative to the repo root.

    Follows the file reference up through its PBXGroup parents, adding each
    group's `path`, so a file in the main group resolves to the project folder
    and a file in a group with path = Tinodios resolves to Tinodios/<file>.
    Returns "" when the project does not reference the file.
    """
    text = open(os.path.join(project, "project.pbxproj"), encoding="utf-8").read()
    ref = re.search(r'^\s*(\w{24})(?: /\*.*?\*/)? = \{isa = PBXFileReference;[^}]*?\bpath = "?'
                    + re.escape(FIREBASE_PLIST) + r'"?;', text, re.M)
    if not ref:
        return ""
    groups = {}
    for m in re.finditer(r'^\t\t(\w{24})(?: /\*.*?\*/)? = \{\n\t\t\tisa = PBXGroup;(.*?)^\t\t\};', text, re.M | re.S):
        body = m.group(2)
        children = re.search(r"children = \((.*?)\);", body, re.S)
        path = re.search(r'^\t\t\tpath = (?:"([^"]*)"|([^;]+));', body, re.M)
        source_tree = re.search(r'^\t\t\tsourceTree = (?:"([^"]*)"|([^;]+));', body, re.M)
        groups[m.group(1)] = {
            "children": re.findall(r"\b(\w{24})\b", children.group(1)) if children else [],
            "path": (path.group(1) or path.group(2)).strip() if path else "",
            "root": bool(source_tree and (source_tree.group(1) or source_tree.group(2)) == "SOURCE_ROOT"),
        }
    parent = {child: gid for gid, g in groups.items() for child in g["children"]}
    parts, current = [], ref.group(1)
    while current in parent:
        group = groups[parent[current]]
        if group["path"]:
            parts.append(group["path"])
        if group["root"]:
            break
        current = parent[current]
    parts.reverse()
    return os.path.normpath(os.path.join(os.path.dirname(project) or ".", *parts, FIREBASE_PLIST)).replace(os.sep, "/")


def main():
    flag, container = choose_container()
    print(f"Build container : {flag} {container}")
    scheme, project = choose_scheme(flag, container)
    print(f"Scheme          : {scheme} (defined in {project})")
    plist = firebase_plist_path(project)
    print(f"Firebase plist  : {plist or 'not referenced by the project'}")

    values = {
        "BUILD_CONTAINER_FLAG": flag,
        "BUILD_CONTAINER": container,
        "SCHEME": scheme,
        "SCHEME_PROJECT": project,
        "FIREBASE_PLIST_PATH": plist,
    }
    target = os.environ.get("GITHUB_ENV")
    with (open(target, "a", encoding="utf-8") if target else sys.stdout) as out:
        for key, value in values.items():
            out.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
