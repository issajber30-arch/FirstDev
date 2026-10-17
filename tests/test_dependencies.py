# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from firstdev.pipelines.repo_analyzer import parse_dependencies


def test_pyproject_pep621_and_poetry():
    toml = """
[project]
dependencies = ["FastAPI>=0.110", "pydantic[email]~=2.0 ; python_version>'3.9'"]
[project.optional-dependencies]
dev = ["pytest>=8"]
[tool.poetry.dependencies]
python = "^3.12"
Django = "^5"
"""
    got = parse_dependencies({"pyproject.toml": toml})
    assert {"fastapi", "pydantic", "pytest", "django"} <= set(got)


def test_package_json():
    pj = '{"dependencies": {"React": "^18"}, "devDependencies": {"jest": "1"}}'
    assert parse_dependencies({"web/package.json": pj}) == ["jest", "react"]


def test_requirements_strips_comments_options_specifiers():
    txt = (
        "# c\n-r other.txt\n--index-url x\nFlask==2.0  # web\nrequests[socks]>=2\n"
        "numpy ; sys_platform=='x'\n"
    )
    assert parse_dependencies({"requirements-dev.txt": txt}) == ["flask", "numpy", "requests"]


def test_go_mod_and_cargo():
    gomod = (
        "module x\n\nrequire github.com/gin-gonic/gin v1.9.1\nrequire (\n"
        "\tgithub.com/a/b/c v1\n\tgolang.org/x/text v0.1\n)\n"
    )
    cargo = '[package]\nname="x"\n[dependencies]\ntokio = "1"\nserde = { version = "1" }\n'
    got = parse_dependencies({"go.mod": gomod, "Cargo.toml": cargo})
    assert {"gin-gonic/gin", "b/c", "tokio", "serde"} <= set(got)


def test_malformed_files_skipped():
    got = parse_dependencies(
        {"pyproject.toml": "[[[", "package.json": "{nope", "requirements.txt": "flask\n"}
    )
    assert got == ["flask"]


def test_non_dict_json_and_unknown_files_ignored():
    assert parse_dependencies({"package.json": "[1,2]", "README.md": "flask"}) == []


def test_cap_200():
    txt = "\n".join(f"pkg{i:04d}" for i in range(500))
    assert len(parse_dependencies({"requirements.txt": txt})) == 200
