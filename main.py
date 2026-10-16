import sys

if __name__ == "__main__":
    if sys.argv[1:2] == ["--apply-update"]:
        # The portable self-update helper: no window, no Qt (see nimbus/swap.py).
        from nimbus.swap import main as apply_update
        sys.exit(apply_update(sys.argv[2:]))
    from nimbus.ui.app import main
    sys.exit(main())
