from gridpulse.cli import dispatch, parser
from gridpulse.config import Settings
from gridpulse.models.registry import alias_version


def main():
    settings = Settings()
    if alias_version(settings, settings.model_alias) is None:
        print(dispatch(parser().parse_args(["demo"]), settings))
    else:
        print("Approved model already exists; bootstrap skipped")


if __name__ == "__main__":
    main()
