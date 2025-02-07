#!/usr/bin/env python

import click
from penntry import Penntry

class Greeter:
    def __init__(self, name):
        self.name = name

    def greet(self, value):
        print(f"{self.name} is worth {float(value)}")


@click.command()
@click.option("--option")
def cli(option):
    name, value = option.split(":")
    greeter = Greeter(name)
    greeter.greet(value)


with Penntry():
    cli()
