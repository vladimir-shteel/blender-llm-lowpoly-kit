"""Development-only tools of the kit. Nothing in lpk imports lpk_dev, so the kit runs without it, and
.gitattributes marks lpk_dev, dev/ and tests/ export-ignore: git archive and the release archives leave
them out.

fingerprint snapshots every array a stage leaves on a built model and compares two snapshots, for the
same-version determinism check (CONTRIBUTING.md, 'Verifying a change').

Inside Blender, bootstrap as for lpk, purging lpk_dev too:

    for name in [n for n in sys.modules if n == 'lpk' or n.startswith(('lpk.', 'lpk_'))]:
        del sys.modules[name]
    from lpk_dev import fingerprint
    fingerprint.snapshot({'model': '<Name>'}, r'<out>.npz')
"""
