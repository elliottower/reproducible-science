"""Build the web page into `src/repro_ui/static` before a wheel or an sdist is made.

The page is a Vite project under `web/`. Its built files are not in git, so a wheel built from
a checkout has to build them first, and that needs Node and npm. An sdist carries the built
files, so a wheel built from an sdist needs neither. An editable install skips the build: the
page is then built by hand with `npm run build` in `web/`.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

HERE = pathlib.Path(__file__).resolve().parent
WEB = HERE / "web"
STATIC = HERE / "src" / "repro_ui" / "static"


class WebBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if version == "editable" or (STATIC / "index.html").is_file():
            return
        npm = shutil.which("npm")
        if npm is None or not (WEB / "package.json").is_file():
            raise RuntimeError(
                "reproducible-science-ui: the web page is not built and cannot be: "
                "building it needs npm and web/. Run `npm ci && npm run build` in packages/ui/web."
            )
        subprocess.run([npm, "ci"], cwd=WEB, check=True)
        subprocess.run([npm, "run", "build"], cwd=WEB, check=True)
