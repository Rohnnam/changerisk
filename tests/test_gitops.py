import pytest

from changerisk import gitops
from changerisk.gitops import GitError
from changerisk.models import ADDED, DELETED, MODIFIED, RENAMED


def seed(repo):
    repo.write("app.py", "print('one')\n")
    repo.write("README.md", "# demo\n")
    return repo.commit("initial")


def test_range_diff_is_what_the_branch_introduces(repo):
    seed(repo)
    repo.branch("feature")
    repo.write("app.py", "print('two')\n")
    repo.write("extra.py", "x = 1\n")
    repo.commit("work on feature")
    repo.checkout("main")
    repo.write("README.md", "# demo\nmain moved on\n")
    repo.commit("unrelated change on main")

    cs = gitops.load_changes(repo.root, "main", "feature")

    assert {f.path for f in cs.files} == {"app.py", "extra.py"}  # README is main's, not ours
    status = {f.path: f.status for f in cs.files}
    assert status == {"app.py": MODIFIED, "extra.py": ADDED}
    assert [c.subject for c in cs.commits] == ["work on feature"]
    assert cs.merge_base != cs.base_sha
    assert "app.py" in cs.repo_files and "extra.py" in cs.repo_files


def test_deleted_and_renamed_files(repo):
    repo.write("old_name.py", "".join(f"line {i}\n" for i in range(30)))
    repo.write("doomed.txt", "bye\n")
    repo.commit("initial")
    repo.branch("topic")
    repo.git("mv", "old_name.py", "new_name.py")
    repo.remove("doomed.txt")
    repo.commit("rename and delete")

    cs = gitops.load_changes(repo.root, "main", "topic")
    by_path = {f.path: f for f in cs.files}

    assert by_path["new_name.py"].status == RENAMED
    assert by_path["new_name.py"].old_path == "old_name.py"
    assert by_path["doomed.txt"].status == DELETED
    assert by_path["doomed.txt"].deletions == 1


def test_awkward_file_names(repo):
    seed(repo)
    repo.branch("topic")
    repo.write("dir with space/my file.txt", "a\n")
    repo.write("café.txt", "b\n")
    repo.commit("odd names")

    cs = gitops.load_changes(repo.root, "main", "topic")
    assert {f.path for f in cs.files} == {"dir with space/my file.txt", "café.txt"}


def test_crlf_files_do_not_leak_carriage_returns(repo):
    repo.write("win.txt", b"one\r\ntwo\r\n")
    repo.commit("initial")
    repo.branch("topic")
    repo.write("win.txt", b"one\r\ntwo\r\nthree\r\n")
    repo.commit("add a line")

    cs = gitops.load_changes(repo.root, "main", "topic")
    (fc,) = cs.files
    assert [line.text for line in fc.added_lines()] == ["three"]


def test_staged_and_worktree_modes(repo):
    seed(repo)
    repo.write("app.py", "print('staged')\n")
    repo.git("add", "app.py")
    repo.write("README.md", "# demo\nunstaged\n")
    repo.write("fresh.py", "new = True\n")  # untracked

    staged = gitops.load_changes(repo.root, mode="staged")
    assert {f.path for f in staged.files} == {"app.py"}

    work = gitops.load_changes(repo.root, mode="worktree")
    assert {f.path for f in work.files} == {"app.py", "README.md", "fresh.py"}
    fresh = next(f for f in work.files if f.path == "fresh.py")
    assert fresh.status == ADDED and fresh.additions == 1


def test_staged_mode_in_a_repo_with_no_commits(repo):
    repo.write("first.py", "a = 1\n")
    repo.git("add", "first.py")
    cs = gitops.load_changes(repo.root, mode="staged")
    assert [f.path for f in cs.files] == ["first.py"]


def test_default_base_prefers_main_then_master(repo):
    seed(repo)
    assert gitops.default_base(repo.root) == "main"


def test_default_base_none_when_nothing_matches(repo):
    repo.git("checkout", "-q", "-b", "trunk")
    repo.write("a", "1\n")
    repo.commit("c")
    assert gitops.default_base(repo.root) is None
    with pytest.raises(GitError, match="base branch"):
        gitops.load_changes(repo.root)


def test_unknown_revision_message_is_actionable(repo):
    seed(repo)
    with pytest.raises(GitError, match="unknown revision 'nope'"):
        gitops.load_changes(repo.root, "nope", "HEAD")


@pytest.mark.parametrize("ref", ["--upload-pack=evil", "", "a b", "x;rm", "-1"])
def test_hostile_refs_are_rejected_before_git_sees_them(repo, ref):
    seed(repo)
    with pytest.raises(GitError):
        gitops.resolve(repo.root, ref)


def test_not_a_repository(tmp_path):
    with pytest.raises(GitError, match="not inside a git repository"):
        gitops.repo_root(tmp_path)


def test_repo_name_comes_from_remote_when_present(repo):
    seed(repo)
    assert gitops.repo_name(repo.root) == repo.root.name
    repo.git("remote", "add", "origin", "git@github.com:acme/ledgerline.git")
    assert gitops.repo_name(repo.root) == "ledgerline"


def test_no_shared_history_is_explained(repo):
    seed(repo)
    repo.git("checkout", "-q", "--orphan", "island")
    repo.write("other.txt", "x\n")
    repo.commit("island commit")
    with pytest.raises(GitError, match="share no history"):
        gitops.load_changes(repo.root, "main", "island")
