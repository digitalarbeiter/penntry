.PHONY: run clean all break

run:
	sanic web -H 0.0.0.0 --dev

all: clean run break

clean:
	rm events

break:
	python3 broken.py || true
	python someprog.py --option foo:bar || true
