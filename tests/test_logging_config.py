import logging

from manufacturing_monitor.logging_config import configure_logging


def test_default_logging_is_quiet(capsys):
    try:
        configure_logging(verbose=False, log_file=None)
        logging.getLogger("manufacturing_monitor.api").info("hidden")

        assert "hidden" not in capsys.readouterr().err
    finally:
        configure_logging(verbose=False, log_file=None)


def test_verbose_and_log_file_use_expected_detail_levels(tmp_path, capsys):
    log_path = tmp_path / "logs" / "manufacturing-monitor.log"
    logger = logging.getLogger("manufacturing_monitor.api")

    try:
        configure_logging(verbose=True, log_file=log_path)
        logger.debug("debug detail")
        logger.info("console detail")

        stderr = capsys.readouterr().err
        file_log = log_path.read_text(encoding="utf-8")

        assert "console detail" in stderr
        assert "debug detail" not in stderr
        assert "console detail" in file_log
        assert "debug detail" in file_log
    finally:
        configure_logging(verbose=False, log_file=None)
