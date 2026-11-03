# Third-party notices

RackHelm FleetOS itself is licensed under the MIT License (see [LICENSE](LICENSE)).

The project **bundles no third-party source code**. The packages below are
ordinary dependencies resolved by `pip` at install time from the version ranges
in `pyproject.toml`. Their copyright stays with their respective authors and they
are used under their own licenses.

Every license listed is permissive (MIT, BSD-3-Clause, Apache-2.0 or PSF-2.0); none
is copyleft, so shipping this project does not oblige you to publish your own source.
Apache-2.0 dependencies require retaining their `NOTICE` file if you redistribute
them in binary form.

| Package | Version | License |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| fastapi | 0.162.0 | MIT |
| h11 | 0.16.0 | MIT License |
| idna | 3.20 | BSD-3-Clause |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| pydantic | 2.14.2 | MIT |
| pydantic_core | 2.50.2 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |

Runtime dependency count: 14.

Regenerate after changing dependencies:

```bash
python -m pip install pip-licenses
pip-licenses --format=markdown --with-urls --ignore-package rackhelm-fleetos
```

This is an engineering inventory, not legal advice. If you ship a compiled
bundle, confirm the license of each exact version you distribute.
