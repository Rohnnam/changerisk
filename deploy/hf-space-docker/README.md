---
title: ChangeRisk
colorFrom: gray
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Score a code change and see what to test
---

# ChangeRisk

Paste a diff or give a public GitHub pull request, and ChangeRisk scores how risky the change is
and lists what to test because of it: edited configuration, removed tests, loosened dependencies,
committed secrets, destructive migrations, weakened pipelines.

Diffs are analysed in memory and are not stored or logged. Reports stay in your browser.

It also runs locally on private repositories, as a command-line tool and as a GitHub Action.
Source, install instructions and the rule reference: https://github.com/Rohnnam/changerisk

This Space is built from that repository by the `Dockerfile` next to this file.
