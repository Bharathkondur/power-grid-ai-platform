from gridpulse.cli import acquire, parser
from gridpulse.config import Settings

print(acquire(parser().parse_args(["data"]), Settings()))
