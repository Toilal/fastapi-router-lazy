# CHANGELOG

<!-- version list -->

## v0.2.4 (2026-10-08)

### Bug Fixes

- **variants**: Leave no child residue on parent RouterWrappers
  ([#25](https://github.com/Toilal/fastapi-router-lazy/pull/25),
  [`5ffdcb9`](https://github.com/Toilal/fastapi-router-lazy/commit/5ffdcb9d2a4c595b6ebbdd74c2aebbd6dbf6c563))


## v0.2.3 (2026-10-08)

### Bug Fixes

- Rebuild loaded routes from their effective include context
  ([#23](https://github.com/Toilal/fastapi-router-lazy/pull/23),
  [`11f1c6a`](https://github.com/Toilal/fastapi-router-lazy/commit/11f1c6a9d870037ab7d6ee15a00de6b2252d7ae8))

- **extractor**: Register routes reached through nested includes
  ([#23](https://github.com/Toilal/fastapi-router-lazy/pull/23),
  [`11f1c6a`](https://github.com/Toilal/fastapi-router-lazy/commit/11f1c6a9d870037ab7d6ee15a00de6b2252d7ae8))

- **router-loader**: Keep effective contexts off the caller's wrappers
  ([#23](https://github.com/Toilal/fastapi-router-lazy/pull/23),
  [`11f1c6a`](https://github.com/Toilal/fastapi-router-lazy/commit/11f1c6a9d870037ab7d6ee15a00de6b2252d7ae8))

- **router-loader**: Rebuild loaded routes from their effective include context
  ([#23](https://github.com/Toilal/fastapi-router-lazy/pull/23),
  [`11f1c6a`](https://github.com/Toilal/fastapi-router-lazy/commit/11f1c6a9d870037ab7d6ee15a00de6b2252d7ae8))


## v0.2.2 (2026-07-25)

### Bug Fixes

- **router-loader**: Isolate reparented routes
  ([#20](https://github.com/Toilal/fastapi-router-lazy/pull/20),
  [`b31933a`](https://github.com/Toilal/fastapi-router-lazy/commit/b31933a4738d80f3536eed0908433b7c8d623535))

- **router-loader**: Preserve dependency overrides
  ([#20](https://github.com/Toilal/fastapi-router-lazy/pull/20),
  [`b31933a`](https://github.com/Toilal/fastapi-router-lazy/commit/b31933a4738d80f3536eed0908433b7c8d623535))


## v0.2.1 (2026-07-20)

### Bug Fixes

- Flatten _IncludedRouter wrappers into serving routes
  ([#18](https://github.com/Toilal/fastapi-router-lazy/pull/18),
  [`62b6788`](https://github.com/Toilal/fastapi-router-lazy/commit/62b678874cc071832914c3e083bf5fab2c693d6f))


## v0.2.0 (2026-07-05)

### Features

- Support Python 3.11 ([#16](https://github.com/Toilal/fastapi-router-lazy/pull/16),
  [`ae5a84d`](https://github.com/Toilal/fastapi-router-lazy/commit/ae5a84db7749cc42edc0d4a31041a35a61c2841d))


## v0.1.0 (2026-07-05)

- Initial Release

Changelog entries are generated automatically by
[python-semantic-release](https://python-semantic-release.readthedocs.io/) from
[Conventional Commits](https://www.conventionalcommits.org/) on release.
