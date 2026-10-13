.PHONY: build-base build-runner build-base-host build-runner-host build build-host check-runner-image smoke comprehensive comprehensive-indirect export-runner import-runner clean

D4J_BASE_IMAGE ?= localhost/d4j-base:latest
D4J_RUNNER_IMAGE ?= localhost/d4j-runner:latest
CONTAINER_RUNTIME ?= podman
BASE_IMAGE ?= ubuntu:24.04
PROXY ?=
NO_PROXY ?= localhost,127.0.0.1
BUILD_NETWORK ?=
RUN_NETWORK ?=
EXPORT_DIR ?= .cache/export
RUNNER_TAR ?= $(EXPORT_DIR)/d4j-runner_latest.tar

BUILD_COMMON_ARGS := --http-proxy=false
BUILD_HOST_ARGS := --network=host

BUILD_PROXY_ARGS :=
ifneq ($(strip $(PROXY)),)
BUILD_PROXY_ARGS += --build-arg http_proxy=$(PROXY) --build-arg https_proxy=$(PROXY)
BUILD_PROXY_ARGS += --build-arg HTTP_PROXY=$(PROXY) --build-arg HTTPS_PROXY=$(PROXY)
BUILD_PROXY_ARGS += --build-arg no_proxy=$(NO_PROXY) --build-arg NO_PROXY=$(NO_PROXY)
endif

BUILD_NETWORK_ARGS :=
ifneq ($(strip $(BUILD_NETWORK)),)
BUILD_NETWORK_ARGS += --network=$(BUILD_NETWORK)
endif

build-base:
	$(CONTAINER_RUNTIME) build $(BUILD_COMMON_ARGS) -f defects4j/Dockerfile -t $(D4J_BASE_IMAGE) --build-arg BASE_IMAGE=$(BASE_IMAGE) $(BUILD_PROXY_ARGS) $(BUILD_NETWORK_ARGS) .

build-runner:
	$(CONTAINER_RUNTIME) build $(BUILD_COMMON_ARGS) -f Dockerfile -t $(D4J_RUNNER_IMAGE) --build-arg D4J_BASE_IMAGE=$(D4J_BASE_IMAGE) $(BUILD_PROXY_ARGS) $(BUILD_NETWORK_ARGS) .

build-base-host:
	$(CONTAINER_RUNTIME) build $(BUILD_HOST_ARGS) -f defects4j/Dockerfile -t $(D4J_BASE_IMAGE) --build-arg BASE_IMAGE=$(BASE_IMAGE) .

build-runner-host:
	$(CONTAINER_RUNTIME) build $(BUILD_HOST_ARGS) -f Dockerfile -t $(D4J_RUNNER_IMAGE) --build-arg D4J_BASE_IMAGE=$(D4J_BASE_IMAGE) .

build: build-base build-runner

build-host: build-base-host build-runner-host

check-runner-image:
	@$(CONTAINER_RUNTIME) image exists $(D4J_RUNNER_IMAGE) || (echo "Runner image not found: $(D4J_RUNNER_IMAGE). Run 'make build' first." >&2; exit 2)

smoke: check-runner-image
	CONTAINER_RUNTIME=$(CONTAINER_RUNTIME) PROXY='$(PROXY)' NO_PROXY='$(NO_PROXY)' RUN_NETWORK='$(RUN_NETWORK)' python3 ./scripts/smoke_test.py --image $(D4J_RUNNER_IMAGE)

comprehensive: check-runner-image
	python3 ./scripts/comprehensive_test_container.py --mode direct --image $(D4J_RUNNER_IMAGE) --runtime $(CONTAINER_RUNTIME)

comprehensive-indirect: check-runner-image
	python3 ./scripts/comprehensive_test_container.py --mode indirect --image $(D4J_RUNNER_IMAGE) --runtime $(CONTAINER_RUNTIME)

export-runner:
	mkdir -p $(EXPORT_DIR)
	$(CONTAINER_RUNTIME) save -o $(RUNNER_TAR) $(D4J_RUNNER_IMAGE)
	@echo "Saved: $(RUNNER_TAR)"

import-runner:
	test -f $(RUNNER_TAR) || (echo "Runner tar not found: $(RUNNER_TAR)" >&2; exit 2)
	$(CONTAINER_RUNTIME) load -i $(RUNNER_TAR)

clean:
	rm -rf ./.cache
