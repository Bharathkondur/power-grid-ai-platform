from gridpulse.cli import dispatch, parser
from gridpulse.config import Settings

print(dispatch(parser().parse_args(["features"]), Settings()))
