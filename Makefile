.PHONY: check test package-extension package-source clean

check:
	python3 -m compileall -q native_host tests
	python3 scripts/check_public_hygiene.py
	python3 -c 'import json; json.load(open("extension/manifest.json", encoding="utf-8"))'
	bash -n install_native_host.sh native_host/launcher.sh scripts/publish_to_github.sh
	@for f in extension/*.js; do node --check "$$f"; done

test:
	python3 -m pytest

package-extension:
	python3 scripts/package_extension.py

package-source:
	python3 scripts/package_source.py

clean:
	rm -rf dist .pytest_cache native_host/__pycache__ tests/__pycache__
