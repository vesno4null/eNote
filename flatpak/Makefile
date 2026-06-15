APP_ID = io.github.vesno4null.enote

all: build

build:
	flatpak-builder --user --install --force-clean build-dir $(APP_ID).yml

run:
	flatpak run $(APP_ID)

export:
	flatpak build-export repo build-dir

.PHONY: all build run export
