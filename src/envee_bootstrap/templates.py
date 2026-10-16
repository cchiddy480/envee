"""Small, composable starters; no remote template execution."""

from dataclasses import asdict
import json
from pathlib import Path
from textwrap import dedent

from . import __version__
from .model import Options
from .agent_tools import IGNORE_PATTERNS


def text(value):
    return dedent(value).strip() + "\n"


def js(value):
    return json.dumps(value, indent=2) + "\n"


def python_files(o: Options):
    kind = o.backend
    deps = {
        "flask": ["Flask==3.1.3"],
        "fastapi": ["fastapi==0.143.0", "uvicorn==0.54.0"],
        "cli": ["click==8.4.2", "rich==15.0.0"],
        "python": [],
    }[kind]
    if o.database == "sqlite":
        deps.append("SQLAlchemy==2.0.50")
    runtime_dependencies = deps.copy()
    if o.lint:
        deps.extend(["pylint==4.0.6", "black==25.1.0"])
    if o.tests:
        deps.append("pytest==9.1.1")
        if kind == "fastapi":
            deps.append("httpx==0.28.1")
    f = {"requirements.txt": "\n".join(deps) + "\n", "app/__init__.py": ""}
    if kind == "flask":
        f["app/main.py"] = text('''
            """HTTP API starter."""

            from flask import Flask


            def create_app():
                """Build an isolated application instance."""
                app = Flask(__name__)

                @app.get("/api/health")
                def health():
                    return {"status": "ok"}

                return app
        ''')
        test = '''
            """Check the public health endpoint."""
            from app.main import create_app


            def test_health():
                response = create_app().test_client().get("/api/health")
                assert response.status_code == 200
                assert response.json == {"status": "ok"}
        '''
    elif kind == "fastapi":
        f["app/main.py"] = text('''
            """HTTP API starter."""

            from fastapi import FastAPI

            app = FastAPI()


            @app.get("/api/health")
            def health():
                """Report application health."""
                return {"status": "ok"}
        ''')
        test = '''
            """Check the public health endpoint."""
            from fastapi.testclient import TestClient
            from app.main import app


            def test_health():
                response = TestClient(app).get("/api/health")
                assert response.status_code == 200
                assert response.json() == {"status": "ok"}
        '''
    elif kind == "cli":
        f["app/main.py"] = text('''
            """Your command-line application."""

            import click
            from rich.console import Console


            @click.command()
            @click.option("--name", default="world", help="Who to greet.")
            def main(name):
                """Print a greeting."""
                Console().print(f"Hello, {name}!", markup=False)


            if __name__ == "__main__":
                main()  # pylint: disable=no-value-for-parameter; Click supplies the arguments.
        ''')
        test = '''
            """Check command arguments and output."""
            from click.testing import CliRunner
            from app.main import main


            def test_greeting():
                result = CliRunner().invoke(main, ["--name", "team"])
                assert result.exit_code == 0
                assert "Hello, team!" in result.output
        '''
    else:
        f["app/main.py"] = text('''
            """Your Python project."""


            def greeting(name="world"):
                """Build a greeting."""
                return f"Hello, {name}!"


            if __name__ == "__main__":
                print(greeting())
        ''')
        test = '''
            """Check the starter's public function."""
            from app.main import greeting


            def test_greeting():
                assert greeting("team") == "Hello, team!"
        '''
    f["pyproject.toml"] = text(f'''
        [build-system]
        requires = ["setuptools>=77"]
        build-backend = "setuptools.build_meta"

        [project]
        name = "{o.name}"
        version = "0.1.0"
        requires-python = ">=3.12"
        dependencies = {json.dumps(runtime_dependencies)}

        [tool.setuptools.packages.find]
        include = ["app*"]

        [tool.pytest.ini_options]
        testpaths = ["tests"]

        [tool.black]
        line-length = 88
    ''')
    if kind == "cli":
        f["pyproject.toml"] += f'\n[project.scripts]\n{o.name} = "app.main:main"\n'
    if o.tests:
        f["tests/test_app.py"] = text(test)
    if o.lint:
        f[".pylintrc"] = text("""
            [MESSAGES CONTROL]
            disable=too-few-public-methods
        """)
    if o.database == "sqlite":
        f["app/main.py"] = (
            f["app/main.py"]
            .replace(
                "from flask import Flask" if kind == "flask" else "from fastapi import FastAPI",
                ("from flask import Flask" if kind == "flask" else "from fastapi import FastAPI")
                + "\nfrom .database import check_database",
            )
            .replace(
                'return {"status": "ok"}',
                "check_database()\n"
                + ("        " if kind == "flask" else "    ")
                + 'return {"status": "ok"}',
            )
        )
        f["app/database.py"] = text('''
            """A local SQLite database; no external server required."""

            import os
            from pathlib import Path
            from sqlalchemy import create_engine, text


            def check_database():
                """Create the local data directory and check a connection."""
                Path("data").mkdir(exist_ok=True)
                engine = create_engine(os.environ.get("DATABASE_URL", "sqlite:///data/app.db"))
                try:
                    with engine.connect() as connection:
                        return connection.execute(text("SELECT 1")).scalar() == 1
                finally:
                    engine.dispose()
        ''')
        if o.tests:
            f["tests/test_database.py"] = text('''
                """Check SQLite without writing to the real data directory."""
                from app.database import check_database


                def test_database(tmp_path, monkeypatch):
                    monkeypatch.chdir(tmp_path)
                    assert check_database()
            ''')
    return f


def node_files(o: Options, kind):
    web = kind == "web"
    f = {}
    scripts = {"build": "tsc"}
    deps = {}
    dev = {"typescript": "5.9.3", "@types/node": "22.20.5"}
    if web:
        deps = {"vue": "3.5.44", "quasar": "2.35.1", "pinia": "4.1.0", "vue-router": "5.4.0"}
        dev.update(
            {
                "vite": "8.3.4",
                "@vitejs/plugin-vue": "6.0.10",
                "@quasar/vite-plugin": "2.0.2",
                "sass-embedded": "1.105.1",
                "vue-tsc": "3.3.7",
            }
        )
        scripts.update(
            {
                "dev": "vite --host 0.0.0.0",
                "build": "vue-tsc --noEmit && vite build",
                "preview": "vite preview --host 0.0.0.0",
            }
        )
        f["index.html"] = text(f"""
            <!doctype html>
            <html lang="en">
              <head>
                <meta charset="UTF-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1.0" />
                <title>{o.name}</title>
              </head>
              <body><div id="app"></div><script type="module" src="/src/main.ts"></script></body>
            </html>
        """)
        f["src/main.ts"] = text("""
            import { createApp } from 'vue'
            import { createPinia } from 'pinia'
            import { Quasar } from 'quasar'
            import 'quasar/src/css/index.sass'
            import './style.css'
            import App from './App.vue'
            import { router } from './router'

            createApp(App).use(createPinia()).use(router).use(Quasar, {}).mount('#app')
        """)
        f["src/router.ts"] = text("""
            import { createRouter, createWebHistory } from 'vue-router'
            import Home from './Home.vue'

            export const router = createRouter({
              history: createWebHistory(),
              routes: [{ path: '/', component: Home }],
            })
        """)
        f["src/App.vue"] = "<template><router-view /></template>\n"
        f["src/Home.vue"] = text(f"""
            <script setup lang="ts">
            import {{ ref }} from 'vue'

            const status = ref('Ready to build')
            const loading = ref(false)
            async function checkApi() {{
              loading.value = true
              status.value = 'Connecting…'
              try {{
                const response = await fetch('/api/health')
                if (!response.ok) throw new Error('API unavailable')
                const data = await response.json()
                status.value = data.status === 'ok' ? 'API connected' : 'Unexpected API response'
              }} catch {{
                status.value = 'API unavailable. Check that your backend is running.'
              }} finally {{
                loading.value = false
              }}
            }}
            </script>

            <template>
              <main>
                <p class="eyebrow">Your workspace</p>
                <h1>{o.name}</h1>
                <p class="intro">Everything starts here. Make it yours.</p>
                <section aria-label="Project status">
                  <p role="status">{{{{ status }}}}</p>
                  {'<q-btn color="primary" label="Check API connection" :loading="loading" @click="checkApi" />' if o.fullstack else '<p class="hint">Vue, Quasar and TypeScript are ready.</p>'}
                </section>
              </main>
            </template>
        """)
        # Web-only starters have no API action to avoid a misleading dead button.
        if not o.fullstack:
            f["src/Home.vue"] = f["src/Home.vue"].split("</script>", 1)[1].lstrip()
            f["src/Home.vue"] = f["src/Home.vue"].replace("{{ status }}", "Ready to build")
        f["src/style.css"] = text("""
            :root { font-family: 'Segoe UI', 'Helvetica Neue', sans-serif; color: #18232c; background: #f6f8f9; }
            * { box-sizing: border-box; }
            body { margin: 0; font-family: inherit; }
            .q-btn { min-height: 44px; }
            main { max-width: 960px; margin: 0 auto; padding: 64px 24px; }
            h1 { font-size: clamp(32px, 6vw, 56px); letter-spacing: -0.04em; margin: 8px 0 16px; overflow-wrap: anywhere; }
            .eyebrow { color: #375568; font-size: 12px; text-transform: uppercase; letter-spacing: 0.12em; }
            .intro { font-size: 20px; color: #465866; }
            section { border-top: 1px solid #cbd5dc; margin-top: 40px; padding-top: 24px; }
            .hint { color: #465866; }
            button:focus-visible { outline: 3px solid #126c91; outline-offset: 4px; }
            @media (prefers-color-scheme: dark) {
              :root { color: #edf2f5; background: #14212a; }
              .eyebrow, .intro, .hint { color: #b3c8d6; }
              section { border-color: #425867; }
            }
        """)
        backend_port = 7071 if o.backend == "azure" else 8000
        f["vite.config.ts"] = text(f"""
            import {{ defineConfig }} from 'vite'
            import vue from '@vitejs/plugin-vue'
            import {{ quasar, transformAssetUrls }} from '@quasar/vite-plugin'

            export default defineConfig({{
              plugins: [vue({{ template: {{ transformAssetUrls }} }}), quasar()],
              server: {{
                port: 5173,
                strictPort: true,
                {'proxy: { "/api": { target: process.env.API_PROXY_TARGET || "http://127.0.0.1:' + str(backend_port) + '", changeOrigin: true } },' if o.fullstack else ""}
              }},
            }})
        """)
        f["src/env.d.ts"] = '/// <reference types="vite/client" />\n'
        f["tsconfig.json"] = js(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "ESNext",
                    "moduleResolution": "Bundler",
                    "strict": True,
                    "skipLibCheck": True,
                    "noEmit": True,
                    "lib": ["ES2022", "DOM"],
                    "types": ["vite/client", "node"],
                },
                "include": ["src/**/*.ts", "src/**/*.vue", "vite.config.ts"],
            }
        )
        f["DESIGN.md"] = text("""
            # Starter design

            Layout: left-aligned project title, introduction, status and one primary action.
            System sans typography; 32–56px title, 20px introduction, 16px body.
            Spacing: 4px/8px grid. Content width: 960px. Page gutter: 24px.
            Neutral backgrounds; primary accent #1976d2. Control radius: 4px.
            Support system dark mode. Status messages use aria-live via role=status.
            Keep the starter small; replace its content as the product takes shape.
        """)
    elif kind == "azure":
        deps["@azure/functions"] = "4.16.5"
        scripts.update({"dev": "npm run build && func start --port 7071", "start": "npm run dev"})
        f["host.json"] = js({"version": "2.0"})
        f["local.settings.example.json"] = js(
            {"IsEncrypted": False, "Values": {"FUNCTIONS_WORKER_RUNTIME": "node", "AzureWebJobsStorage": ""}}
        )
        f["src/health.ts"] = text("""
            import { app, HttpResponseInit } from '@azure/functions'

            export async function health(): Promise<HttpResponseInit> {
              return { status: 200, jsonBody: { status: 'ok' } }
            }

            app.http('health', { methods: ['GET'], authLevel: 'anonymous', handler: health })
        """)
        f["tsconfig.json"] = js(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "CommonJS",
                    "moduleResolution": "Node",
                    "strict": True,
                    "skipLibCheck": True,
                    "outDir": "dist",
                    "rootDir": "src",
                },
                "include": ["src/**/*.ts"],
            }
        )
    else:
        scripts["dev"] = "npm run build && node dist/index.js"
        f["src/index.ts"] = (
            "export const greeting = (name = 'world'): string => `Hello, ${name}!`\nconsole.log(greeting())\n"
        )
        f["tsconfig.json"] = js(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "CommonJS",
                    "strict": True,
                    "skipLibCheck": True,
                    "outDir": "dist",
                    "rootDir": "src",
                },
                "include": ["src/**/*.ts"],
            }
        )
    if o.lint:
        dev.update(
            {"eslint": "10.12.0", "@eslint/js": "10.0.1", "typescript-eslint": "8.71.2", "prettier": "3.9.10"}
        )
        if web:
            dev["eslint-plugin-vue"] = "10.11.1"
        scripts.update(
            {"lint": "eslint .", "format": "prettier --write .", "format:check": "prettier --check ."}
        )
        f["eslint.config.mjs"] = text("""
            import js from '@eslint/js'
            import tseslint from 'typescript-eslint'
        """)
        if web:
            f["eslint.config.mjs"] += "import vue from 'eslint-plugin-vue'\n"
        f["eslint.config.mjs"] += (
            text("""
            export default tseslint.config(
              { ignores: ['dist/**', 'node_modules/**', 'coverage/**', 'scripts/**'] },
              js.configs.recommended,
              ...tseslint.configs.recommended,
        """).rstrip()
            + "\n"
        )
        if web:
            f["eslint.config.mjs"] += text("""
                ...vue.configs['flat/essential'],
                { files: ['**/*.vue'], languageOptions: { parserOptions: { parser: tseslint.parser } },
                  rules: { 'vue/multi-word-component-names': 'off' } },
            """)
        f["eslint.config.mjs"] += text("""
              { languageOptions: { globals: { console: 'readonly', process: 'readonly', fetch: 'readonly' } } },
            )
        """)
        f[".prettierrc.json"] = js({"semi": False, "singleQuote": True, "printWidth": 100})
        f[".prettierignore"] = "dist\nnode_modules\npackage-lock.json\n.venv\ndata\n"
    if o.tests:
        dev["jest"] = "30.5.2"
        scripts["test"] = "npm run build && jest --runInBand"
        f["jest.config.cjs"] = (
            "module.exports = { testEnvironment: 'node', testMatch: ['**/tests/*.test.cjs'] }\n"
        )
        if web:
            # Use a real mounted Vue component, rather than only asserting a build file exists.
            dev.update({"@vue/test-utils": "2.5.1", "@vue/compiler-sfc": "3.5.44", "jsdom": "26.1.0"})
            f["tests/app.test.cjs"] = text("""
                const fs = require('node:fs')
                const path = require('node:path')
                const { JSDOM } = require('jsdom')
                const { window } = new JSDOM('<html><body></body></html>')
                for (const key of ['window', 'document', 'Element', 'HTMLElement', 'SVGElement', 'Node']) {
                  global[key] = window[key]
                }
                const { mount, flushPromises } = require('@vue/test-utils')
                const compiler = require('@vue/compiler-sfc')
                const ts = require('typescript')
                const descriptor = compiler.parse(fs.readFileSync('src/Home.vue', 'utf8')).descriptor
                const source = descriptor.scriptSetup
                  ? compiler.compileScript(descriptor, { id: 'home', inlineTemplate: true }).content
                  : compiler.compileTemplate({ source: descriptor.template.content, id: 'home', filename: 'Home.vue' }).code
                const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
                const loaded = {}
                new Function('require', 'exports', compiled)(require, loaded)
                const Home = loaded.default || { render: loaded.render }
                const options = { global: { stubs: { 'q-btn': { props: ['label'], emits: ['click'], template: '<button @click="$emit(\\\'click\\\')">{{ label }}</button>' } } } }

                test('the actual home screen renders the project name and status', () => {
                  const widget = mount(Home, options)
                  expect(widget.find('h1').text()).toBe('__PROJECT_NAME__')
                  expect(widget.find('[role="status"]').text()).toBe('Ready to build')
                  widget.unmount()
                })

                test('the full-stack action handles successful and failed API requests', async () => {
                  const widget = mount(Home, options)
                  if (!widget.find('button').exists()) { widget.unmount(); return }
                  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok' }) })
                  await widget.find('button').trigger('click')
                  await flushPromises()
                  expect(global.fetch).toHaveBeenCalledWith('/api/health')
                  expect(global.fetch).toHaveBeenCalledTimes(1)
                  expect(widget.find('[role="status"]').text()).toBe('API connected')
                  global.fetch.mockRejectedValueOnce(new Error('offline'))
                  await widget.find('button').trigger('click')
                  await flushPromises()
                  expect(widget.find('[role="status"]').text()).toContain('API unavailable')
                  widget.unmount()
                })

                test('production build references existing assets', () => {
                  const html = fs.readFileSync('dist/index.html', 'utf8')
                  const assets = [...html.matchAll(/(?:src|href)="(\\/assets\\/[^" ]+)"/g)]
                  expect(assets.length).toBeGreaterThan(0)
                  for (const [, asset] of assets) expect(fs.existsSync(path.join('dist', asset))).toBe(true)
                })
            """).replace("__PROJECT_NAME__", o.name)
        elif kind == "azure":
            f["tests/health.test.cjs"] = text("""
                jest.mock('@azure/functions', () => ({ app: { http: jest.fn() } }))
                const { app } = require('@azure/functions')
                const { health } = require('../dist/health')

                test('health endpoint is registered and returns a JSON response', async () => {
                  expect(app.http).toHaveBeenCalledWith('health', expect.objectContaining({ methods: ['GET'] }))
                  expect(await health({}, {})).toEqual({ status: 200, jsonBody: { status: 'ok' } })
                })
            """)
        else:
            f["tests/greeting.test.cjs"] = (
                "const { greeting } = require('../dist/index')\ntest('greets a named user', () => expect(greeting('team')).toBe('Hello, team!'))\n"
            )
        if o.lint:
            f["eslint.config.mjs"] = f["eslint.config.mjs"].replace(
                "...tseslint.configs.recommended,",
                "...tseslint.configs.recommended,\n  { files: ['**/*.cjs'], languageOptions: { globals: { require: 'readonly', module: 'readonly', global: 'readonly', jest: 'readonly', test: 'readonly', expect: 'readonly' } }, rules: { '@typescript-eslint/no-require-imports': 'off' } },",
            )
    package = {
        "name": o.name + ("-web" if web and o.fullstack else ""),
        "version": "0.1.0",
        "private": True,
        "engines": {"node": ">=22.13.0 <23"},
        "scripts": scripts,
        "dependencies": deps,
        "devDependencies": dev,
    }
    if o.tests:
        # NYC uses yaml.load, which is compatible with v4 and avoids the old sprintf-js tree.
        package["overrides"] = {"@istanbuljs/load-nyc-config": {"js-yaml": "4.3.2"}}
    if web:
        package["type"] = "module"
    if kind == "azure":
        package["main"] = "dist/*.js"
    f["package.json"] = js(package)
    f[".nvmrc"] = "22\n"
    return f


def render(o: Options):
    o.validate()
    f = {}
    components = []
    if o.has_python:
        path = "backend" if o.fullstack else "."
        components.append({"path": path, "kind": o.backend})
        f.update({(Path(path) / k).as_posix(): v for k, v in python_files(o).items()})
    if o.backend in {"azure", "typescript"}:
        path = "backend" if o.fullstack else "."
        components.append({"path": path, "kind": o.backend})
        f.update({(Path(path) / k).as_posix(): v for k, v in node_files(o, o.backend).items()})
    if o.has_web:
        path = "frontend" if o.fullstack else "."
        components.append({"path": path, "kind": "web"})
        f.update({(Path(path) / k).as_posix(): v for k, v in node_files(o, "web").items()})
    manifest = {"schema": 1, "envee_version": __version__, **asdict(o), "components": components}
    f["envee.json"] = js(manifest)
    f["scripts/project.py"] = Path(__file__).with_name("project_runner.py").read_text()
    f[".gitignore"] = text("""
        .venv/
        **/.venv/
        __pycache__/
        *.py[cod]
        *.egg-info/
        .pytest_cache/
        .ruff_cache/
        node_modules/
        dist/
        coverage/
        .env
        .env.*
        !.env.example
        local.settings.json
        data/
        .envee/
        .DS_Store
    """)
    if o.codegraph or o.ponytail:
        f[".gitignore"] += "\n# Local agent tools\n" + "\n".join(IGNORE_PATTERNS) + "\n"
        guidance = "# Local development tools\n\n"
        if o.codegraph:
            guidance += ("## CodeGraph\n\nUse CodeGraph before searching or reading unfamiliar code. "
                         "Use the codegraph_explore MCP tool or `codegraph explore` to find symbols "
                         "and call paths. The local `.codegraph/` index is excluded from Git.\n\n")
        if o.ponytail:
            assets = Path(__file__).parent / "assets/ponytail"
            for name in ["SKILL.md", "LICENSE", "SOURCE.md"]:
                f[".agents/skills/ponytail/" + name] = (assets / name).read_text(encoding="utf-8")
            guidance += ("## Ponytail\n\nFor coding work, read `.agents/skills/ponytail/SKILL.md` "
                         "and apply its full mode: the smallest complete solution, with validation "
                         "and necessary checks. Keep these instructions and skills local.\n")
        f["AGENTS.md"] = guidance
    f[".editorconfig"] = text("""
        root = true
        [*]
        charset = utf-8
        end_of_line = lf
        insert_final_newline = true
        indent_style = space
        indent_size = 2
        [*.py]
        indent_size = 4
    """)
    for c in components:
        if o.env:
            f[(Path(c["path"]) / ".env.example").as_posix()] = (
                "DATABASE_URL=sqlite:///data/app.db\n"
                if o.database == "sqlite" and c["kind"] in {"flask", "fastapi"}
                else "# Add local settings here. Keep credentials out of Git.\n"
            )
    if o.editor:
        extensions = []
        if o.has_python:
            extensions.extend(
                ["ms-python.python", "ms-python.black-formatter"] if o.lint else ["ms-python.python"]
            )
        if o.has_node and o.lint:
            extensions.extend(["dbaeumer.vscode-eslint", "esbenp.prettier-vscode"])
        if o.has_web:
            extensions.append("Vue.volar")
        if o.backend == "azure":
            extensions.append("ms-azuretools.vscode-azurefunctions")
        f[".vscode/extensions.json"] = js({"recommendations": extensions})
        f[".vscode/tasks.json"] = js(
            {
                "version": "2.0.0",
                "tasks": [
                    {
                        "label": "Start development",
                        "type": "shell",
                        "command": "python3 scripts/project.py dev",
                    },
                    {
                        "label": "Verify project",
                        "type": "shell",
                        "command": "python3 scripts/project.py check",
                        "group": "test",
                    },
                ],
            }
        )
        if o.has_python:
            f[".vscode/settings.json"] = js(
                {
                    "python.defaultInterpreterPath": "${workspaceFolder}/"
                    + ("backend/" if o.fullstack else "")
                    + ".venv/bin/python"
                }
            )
    container_files(f, o, components)
    if o.ci:
        f[".github/workflows/check.yml"] = text("""
            name: Check project
            on: [push, pull_request]
            permissions:
              contents: read
            jobs:
              check:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@v4
                  - uses: actions/setup-python@v5
                    with:
                      python-version: '3.12'
                  - uses: actions/setup-node@v4
                    with:
                      node-version: '22'
                  - run: python3 scripts/project.py setup --local --skip-runtime
        """)
    f["README.md"] = readme(o, components)
    return f


def container_files(f, o, components):
    if o.environment == "local":
        return
    services = {}
    for c in components:
        path, kind = c["path"], c["kind"]
        python = kind in {"flask", "fastapi", "cli", "python"}
        base = "python:3.12-slim-bookworm" if python else "node:22-bookworm-slim"
        dockerfile = f"FROM {base}\nWORKDIR /workspace\n"
        if kind == "azure":
            dockerfile += "RUN apt-get update && apt-get install -y --no-install-recommends libicu72 libssl3 ca-certificates && rm -rf /var/lib/apt/lists/*\nRUN npm install -g azure-functions-core-tools@4 --unsafe-perm true\n"
        if python:
            dockerfile += 'RUN python -m venv .venv\nENV PATH="/workspace/.venv/bin:$PATH"\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nRUN pip install --no-cache-dir -e .\n'
        else:
            dockerfile += "COPY package*.json .\nRUN npm ci\nCOPY . .\nRUN npm run build\n"
        if kind == "azure":
            dockerfile += "RUN cp local.settings.example.json local.settings.json\n"
        command = {
            "flask": [
                "python",
                "-m",
                "flask",
                "--app",
                "app.main:create_app",
                "run",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            "fastapi": ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
            "cli": ["python", "-m", "app.main"],
            "python": ["python", "-m", "app.main"],
            "typescript": ["node", "dist/index.js"],
            "web": ["npm", "run", "dev"],
            "azure": ["func", "start", "--port", "7071", "--address", "0.0.0.0"],
        }.get(kind)
        if command:
            dockerfile += "CMD " + json.dumps(command) + "\n"
        f[(Path(path) / "Dockerfile").as_posix()] = dockerfile
        f[(Path(path) / ".dockerignore").as_posix()] = (
            ".venv\nnode_modules\ndist\n.git\n.env\n.env.*\nlocal.settings.json\n.envee\ndata\n"
        )
        service = "frontend" if kind == "web" and o.fullstack else "backend" if o.fullstack else "app"
        services[service] = {"build": {"context": path}, "init": True}
        if kind == "web":
            services[service]["ports"] = ["127.0.0.1:5173:5173"]
            if o.fullstack:
                services[service]["environment"] = {
                    "API_PROXY_TARGET": "http://backend:" + ("7071" if o.backend == "azure" else "8000")
                }
                services[service]["depends_on"] = ["backend"]
        elif kind in {"flask", "fastapi", "azure"}:
            services[service]["ports"] = ["127.0.0.1:" + ("7071:7071" if kind == "azure" else "8000:8000")]
        if o.database == "sqlite" and python:
            services[service]["volumes"] = ["database:/workspace/data"]
    compose = {"name": "envee-" + o.name, "services": services}
    if o.database == "sqlite":
        compose["volumes"] = {"database": {}}
    # JSON is valid YAML and avoids another parser dependency.
    f["compose.yaml"] = js(compose)
    if o.environment == "devcontainer":
        f[".devcontainer/Dockerfile"] = text("""
            FROM node:22-bookworm-slim AS node
            FROM python:3.12-bookworm
            COPY --from=node /usr/local/bin/node /usr/local/bin/node
            COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
            RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
                && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
        """)
        if o.backend == "azure":
            f[".devcontainer/Dockerfile"] += (
                "RUN npm install -g azure-functions-core-tools@4 --unsafe-perm true\n"
            )
        f[".devcontainer/devcontainer.json"] = js(
            {
                "name": o.name,
                "build": {"dockerfile": "Dockerfile"},
                "forwardPorts": [5173, 7071 if o.backend == "azure" else 8000]
                if o.fullstack
                else [5173]
                if o.has_web
                else [7071]
                if o.backend == "azure"
                else [8000]
                if o.backend in {"flask", "fastapi"}
                else [],
                "postCreateCommand": "python3 scripts/project.py setup --local",
                "customizations": {
                    "vscode": {
                        "extensions": json.loads(f.get(".vscode/extensions.json", "{}")).get(
                            "recommendations", []
                        )
                    }
                },
            }
        )


def readme(o, components):
    commands = "python3 scripts/project.py dev"
    if o.environment == "devcontainer":
        commands = "Open this folder in VS Code and choose **Dev Containers: Reopen in Container**.\n\nInside the container:\n\n```sh\npython3 scripts/project.py dev\n```"
    else:
        commands = f"```sh\n{commands}\n```"
    return text(f"""
        # {o.name}

        Created with Envee · preset `{o.preset}` · environment `{o.environment}`.

        ## Start developing

        __COMMANDS__

        With Envee installed, use `envee dev` to start, `envee check` to verify,
        `envee doctor` to diagnose prerequisites and `envee setup` to retry setup.
        These work from project subdirectories too. The commands above and below
        also work independently, without installing Envee.

        ## Setup and verification

        ```sh
        python3 scripts/project.py setup
        python3 scripts/project.py check
        ```

        Setup is safe to rerun: it preserves your source and settings, installs dependencies,
        and runs the selected checks. For local setup regardless of environment, add `--local`.
        Ctrl+C stops managed development processes and Docker services. Service URLs appear after readiness checks.
        Images must be rebuilt after source changes; Docker mode does not mount live source.

        ## Requirements

        Local development needs Python 3.12 or newer{", Node 22.13+ (22.x) and npm" if o.has_node else ""}{", and Azure Functions Core Tools v4" if o.backend == "azure" else ""}.
        Docker and Dev Container modes need a running Docker engine and Compose v2.
        Dev Containers also need VS Code's Dev Containers extension. Setup builds and verifies the
        container image; opening it runs local setup in the container.

        {"Web: http://localhost:5173. " if o.has_web else ""}{"API: http://localhost:" + ("7071" if o.backend == "azure" else "8000") + "/api/health." if o.backend in {"flask", "fastapi", "azure"} else ""}
        {"The frontend proxies /api to the backend; use the frontend URL." if o.fullstack else ""}

        ## Project conventions

        {"Python dependencies live in requirements.txt and an isolated .venv in each Python component." if o.has_python else ""}
        {"Commit package-lock.json; setup uses npm ci when it exists." if o.has_node else ""}
        {"The installed Python CLI command is " + o.name + " (activate .venv first), or use python3 scripts/project.py dev." if o.backend == "cli" else ""}
        {"SQLite is wired through app/database.py; its check creates data/app.db. Set DATABASE_URL to override the default." if o.database == "sqlite" else ""}
        Environment files are examples only. Export variables through your shell; .env is not automatically loaded.
        Azure HTTP starters create local.settings.json with no cloud credentials; storage bindings need your own storage settings.
        Never commit .env, local.settings.json, certificates or keys.
        Build and checks are development validation, not deployment or production hardening.
    """).replace("__COMMANDS__", commands)
