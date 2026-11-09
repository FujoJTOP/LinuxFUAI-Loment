# fuai-linux-loment — build and regression entry points.
# Requires a Loment checkout: LOMENT_REPO=/path/to/Loment (clone from GitHub).
LOMENT_REPO ?= ../Loment
export LOMENT_REPO

PYTHON ?= python3

all: build adapters

build:
	$(PYTHON) tools/regress.py --build --bin build

adapters:
	$(MAKE) -C adapters

regress:
	$(PYTHON) tools/regress.py --bin build

clean:
	rm -rf build
	$(MAKE) -C adapters clean

.PHONY: all build adapters regress clean
