# Installation

## Requirements

- Python 3.11+
- No runtime dependencies

## Install

```bash
uv add laddercodec
```

Or with pip:

```bash
pip install laddercodec
```

## Development setup

Clone the repo and install with dev dependencies:

```bash
git clone https://github.com/ssweber/laddercodec.git
cd laddercodec
make install   # uv sync --all-extras --dev
make           # install + lint + test
```
