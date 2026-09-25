"""Security & privacy: secrets check, Docker ports, SSH server, AppArmor, accounts, ClamAV, dev telemetry, file indexing."""

import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pcctl.core import accounts, antivirus, devtelemetry, indexing, secrets, security

FIX = Path(__file__).parent / "fixtures" / "secpriv"


def fx(name: str) -> str:
    return (FIX / name).read_text()


# ---------------------------------------------------------------- secrets: detection + masking

def test_find_secrets_known_formats_and_generic():
    text = fx("bash_history")
    ids = [h.rule.id for h in secrets.find_secrets(text)]
    assert ids.count("openai") == 2                       # typed twice
    assert "bearer" in ids and "mysql" in ids and "github" in ids and "assign" in ids
    assert "url-password" not in ids                      # postgres:postgres@localhost is a default, not a secret
    values = [h.value for h in secrets.find_secrets(text)]
    assert "your_api_key_here" not in values              # placeholders are skipped
    assert not any(v == "-p" for v in values)             # `mysql -p` (asks for the password) is fine


@pytest.mark.parametrize("text,rule", [
    ("key sk-ant-api03-" + "a" * 5 + "B1c2D3e4F5g6H7i8J9k0", "anthropic"),
    ("OPENAI=sk-" + "Ab1" * 16, "openai"),
    ("glpat-" + "x1Y2z3W4v5U6t7S8r9Q0", "gitlab"),
    ("AKIA" + "QWERTYUIOPASDFGH", "aws"),
    ("AIza" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q", "google"),
    ("xoxb-" + "123456789012-abcdefABCDEF", "slack"),
    ("sk_live_" + "51Habcdefghijklmnopqrstuv", "stripe"),
    ("hf_" + "abcdefghijklmnopqrstuvwxyz123456", "huggingface"),
    ("npm_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "npm"),
    ("github_pat_" + "11ABCDEFG0123456789_abcdefghijklmnop", "github-pat"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "private-key"),
    ("sshpass -p Tr0ub4dor ssh me@host", "sshpass"),
    ("CREATE USER bob IDENTIFIED BY 'Sup3rS3cret';", "identified-by"),
    ("git push https://bob:Zx81kLmn0pQ@gitlab.example.net/x.git", None),  # example host → placeholder
])
def test_rules(text, rule):
    hits = secrets.find_secrets(text)
    assert (hits[0].rule.id if hits else None) == rule


def test_mask_never_shows_whole_secret():
    assert secrets.mask("sk-proj-Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56") == "sk-p…56"
    assert secrets.mask("hunter2x") == "hu…"
    assert secrets.mask("abc") == "…"
    line = "export OPENAI_API_KEY=sk-proj-Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56 && curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9xyz'"
    masked = secrets.mask_text(line)
    assert "Ab12Cd34" not in masked and "eyJhbGciOiJIUzI1NiJ9xyz" not in masked and "sk-p…56" in masked


def test_history_findings_and_context():
    fs = secrets.scan_history_text(fx("bash_history"), "/home/u/.bash_history", "terminal history", Path("/home/u"))
    by_rule = {f.rule: f for f in fs}
    oa = by_rule["openai"]
    assert oa.level == "bad" and oa.count == 2 and oa.line == 5
    assert "~/.bash_history line 5 (and 1 more time)" in oa.detail
    assert "Ab12Cd34" not in oa.detail and "sk-p…56" in oa.detail
    assert oa.rotate.startswith("https://platform.openai.com")
    assert by_rule["mysql"].level == "warn" and "S3…" in by_rule["mysql"].detail
    # one scrub step shared by every finding in the file, holding every raw value
    assert all(f.steps and f.steps[0] is fs[0].steps[0] for f in fs)
    for f in fs:
        assert f.raw not in f.detail and f.raw not in f.title and f.raw not in repr(f)


def test_zsh_and_fish_context_strip_prefixes():
    fs = secrets.scan_history_text(fx("zsh_history"), "/h/.zsh_history", "terminal history")
    assert {f.rule for f in fs} == {"anthropic", "aws"}
    assert all(not f.detail.split(": ", 1)[1].startswith(": 17") for f in fs)
    fs = secrets.scan_history_text(fx("fish_history"), "/h/fish_history", "terminal history")
    assert fs[0].rule == "huggingface" and "set -gx HF_TOKEN hf_a…56" in fs[0].detail


def test_scrub_history_formats(tmp_path):
    home = tmp_path
    for name, fmt_file in ((".bash_history", "bash_history"), (".zsh_history", "zsh_history")):
        p = home / name
        p.write_text(fx(fmt_file))
        os.chmod(p, 0o600)
        raws = sorted({h.value for h in secrets.find_secrets(p.read_text())})
        msg = secrets.scrub_history(str(p), raws, home)
        new = p.read_text()
        assert "Removed" in msg
        assert not secrets.find_secrets(new)
        assert oct(p.stat().st_mode & 0o777) == "0o600"
    bash = (home / ".bash_history").read_text().splitlines()
    assert "npm run dev" in bash and "echo done" in bash and "#1727000100" not in bash  # timestamp went with its command
    zsh = (home / ".zsh_history").read_text()
    assert "aws configure set region" not in zsh          # continuation line removed with its entry
    assert ": 1727000030:0;git status" in zsh
    backups = list((home / secrets.BACKUP_DIR_NAME).iterdir())
    assert len(backups) == 2 and all(oct(b.stat().st_mode & 0o777) == "0o600" for b in backups)
    # running it again is harmless
    assert "Nothing to remove" in secrets.scrub_history(str(home / ".bash_history"), ["sk-proj-Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56"], home)


def test_fish_scrub_removes_whole_entry():
    new, n = secrets.scrub_text(fx("fish_history"), ["hf_abcdefghijklmnopqrstuvwxyz123456"], "fish")
    assert n == 1 and "HF_TOKEN" not in new and "- cmd: cd ~/code\n  when: 1727000020\n  paths:\n    - ~/code" in new


def _openssh_key(cipher: bytes) -> str:
    blob = b"openssh-key-v1\0" + len(cipher).to_bytes(4, "big") + cipher + b"\0\0\0\x04none" + b"\0" * 60
    b64 = base64.b64encode(blob).decode()
    return "-----BEGIN OPENSSH PRIVATE KEY-----\n" + "\n".join(b64[i:i + 70] for i in range(0, len(b64), 70)) + "\n-----END OPENSSH PRIVATE KEY-----\n"


def test_key_encrypted():
    assert secrets.key_encrypted(_openssh_key(b"none")) is False
    assert secrets.key_encrypted(_openssh_key(b"aes256-ctr")) is True
    assert secrets.key_encrypted("-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,AB\n\nxx\n-----END RSA PRIVATE KEY-----") is True
    assert secrets.key_encrypted("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----") is False
    assert secrets.key_encrypted("-----BEGIN ENCRYPTED PRIVATE KEY-----\nxx") is True
    assert secrets.key_encrypted("ssh-ed25519 AAAA") is None


@pytest.mark.parametrize("name,kind", [(".env", "env"), (".env.local", "env"), (".env.production", "env"), ("prod.env", "env"),
                                       (".env.example", "env-example"), (".env.sample", "env-example"), ("id_ed25519", "key"),
                                       ("server.pem", "key"), (".npmrc", "rc"), ("firebase-adminsdk-x1.json", "gcp-json"),
                                       ("package.json", ""), ("environment.ts", "")])
def test_classify(name, kind):
    assert secrets.classify(name) == kind


def test_env_secrets_names_only():
    text = "PORT=3000\nOPENAI_API_KEY=sk-proj-Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56\nSTRIPE_KEY=\nDATABASE_URL=postgres://app:Xk29dLq@db.internal/app\n" \
           "API_TOKEN=${TOKEN}\nNEXT_PUBLIC_NAME=shop\nJWT_SECRET=changeme\nSESSION_SECRET=9f8e7d6c5b4a3210\n"
    assert secrets.env_secrets(text) == ["OPENAI_API_KEY", "DATABASE_URL", "SESSION_SECRET"]


def _mk_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".bash_history").write_text(fx("bash_history"))
    key = home / ".ssh/id_ed25519"
    key.write_text(_openssh_key(b"none"))
    os.chmod(key, 0o644)
    (home / ".ssh/id_ed25519.pub").write_text("ssh-ed25519 AAAA me")
    os.chmod(home / ".ssh", 0o755)
    (home / ".aws").mkdir()
    (home / ".aws/credentials").write_text("[default]\naws_access_key_id=AKIAQWERTYUIOPASDFGH\n")
    os.chmod(home / ".aws/credentials", 0o644)
    (home / ".npmrc").write_text("registry=https://registry.npmjs.org/\n")   # no token: not a finding
    os.chmod(home / ".npmrc", 0o644)
    (home / ".git-credentials").write_text("https://ashu:ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8@github.com\n")
    os.chmod(home / ".git-credentials", 0o600)
    os.chmod(home, 0o750)          # Ubuntu's default: other accounts can't enter your home folder
    return home


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), *args], check=True, capture_output=True)


@needs_git
def test_scan_whole_home(tmp_path):
    home = _mk_home(tmp_path)
    code = home / "code"
    # repo A: .env not ignored; repo B: .env committed; repo C: .env ignored (fine); node_modules is skipped
    for name in ("shop", "blog", "safe"):
        (code / name).mkdir(parents=True)
        _git(code / name, "init", "-q")
    (code / "shop/.env").write_text("OPENAI_API_KEY=sk-proj-Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56\n")
    (code / "shop/.env.example").write_text("OPENAI_API_KEY=\n")
    (code / "shop/node_modules/pkg").mkdir(parents=True)
    (code / "shop/node_modules/pkg/.env").write_text("SECRET_TOKEN=abcdefghijklmnop123\n")
    (code / "blog/.env").write_text("SESSION_SECRET=9f8e7d6c5b4a3210\n")
    _git(code / "blog", "add", ".env")
    _git(code / "blog", "commit", "-qm", "oops")
    (code / "safe/.gitignore").write_text(".env\n")
    (code / "safe/.env").write_text("SESSION_SECRET=9f8e7d6c5b4a3210\n")
    (code / "safe/deploy.pem").write_text("-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n")

    fs = secrets.scan(home=home, roots=[code], budget=5)
    titles = [f.title for f in fs]
    assert fs[0].level == "bad"
    assert "Secret settings file that git would upload" in titles
    assert "Secret settings file is saved in git" in titles
    assert "Private key that git would upload" in titles          # deploy.pem in 'safe' isn't ignored
    assert not any("node_modules" in f.path for f in fs)
    assert not any(f.path.endswith("safe/.env") for f in fs)
    assert any(f.title == "~/.aws/credentials can be read by others" and f.level == "bad" for f in fs)
    assert not any(".npmrc" in f.path for f in fs)
    assert any(f.title == "Git passwords saved in plain text" and "ghp_…r8" in f.detail for f in fs)
    assert any(f.title == "SSH private key id_ed25519 can be read by others" for f in fs)
    assert any(f.title == "SSH key id_ed25519 has no passphrase" and f.terminal[:2] == ["ssh-keygen", "-p"] for f in fs)
    assert any(f.id == "ssh-dir" for f in fs)
    assert secrets.LAST["stats"]["seconds"] < 5
    # nothing printed or stored for display contains a full secret
    report = secrets.format_text(fs)
    for raw in ("Ab12Cd34Ef56Gh78Ij90Kl12Mn34Op56", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", "9f8e7d6c5b4a3210", "QWERTYUIOPASDFGH"):
        assert raw not in report
        assert all(raw not in str(f.as_dict()) for f in fs)

    # fixes: .gitignore for 'shop', stop tracking in 'blog', chmod
    tracked = next(f for f in fs if f.title == "Secret settings file is saved in git")
    assert tracked.steps[1].cmd == ["git", "rm", "--cached", "--quiet", "--", ".env"] and tracked.steps[1].cwd == str(code / "blog")
    exposed = next(f for f in fs if f.title == "Secret settings file that git would upload")
    assert "OPENAI_API_KEY" in exposed.detail
    msg = exposed.steps[0]._func()
    assert "Added .env" in msg and (code / "shop/.gitignore").read_text().strip().endswith(".env")
    assert "already lists" in exposed.steps[0]._func()
    assert secrets.git_state(str(code / "shop"), [str(code / "shop/.env")]) == {str(code / "shop/.env"): "ignored"}
    chmod = next(f for f in fs if f.title == "~/.aws/credentials can be read by others")
    assert chmod.steps[0].cmd == ["chmod", "600", str(home / ".aws/credentials")]
    steps = secrets.fix_all_steps(fs)
    assert len([s for s in steps if s.title.startswith("Remove keys from")]) == 1


def test_scan_empty_home_is_ok(tmp_path):
    fs = secrets.scan(home=tmp_path, roots=[tmp_path], budget=2)
    assert fs == []
    assert secrets.summary(fs)[0] == "ok"
    assert "No exposed secrets" in secrets.format_text(fs)
    assert security.secrets_check(fs).level == "ok"


def test_summary_levels():
    f = secrets.Finding("x", "history", "bad", "OpenAI API key in your terminal history", "d")
    lvl, text = secrets.summary([f])
    assert lvl == "bad" and "OpenAI API key" in text
    c = security.secrets_check([f])
    assert c.level == "bad" and c.goto == "security" and c.fix_label


def test_cli_main_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(secrets._run, "HOME", tmp_path)
    (tmp_path / ".bash_history").write_text("export GITHUB_TOKEN=ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8\n")
    monkeypatch.setattr(secrets, "default_roots", lambda home: [])
    rc = secrets.main(["--json"])
    printed = capsys.readouterr().out
    assert rc == 1 and '"rule": "github"' in printed and "A1b2C3d4E5f6" not in printed


# ---------------------------------------------------------------- Docker ports

def test_parse_docker_ports():
    assert security.parse_docker_port_list("0.0.0.0:5432->5432/tcp, :::5432->5432/tcp") == [("0.0.0.0", "5432", "5432", "tcp"), ("::", "5432", "5432", "tcp")]
    assert security.parse_docker_port_list("[::]:8080->3000/tcp, 9229/tcp") == [("[::]", "8080", "3000", "tcp")]
    assert security.parse_docker_port_list("127.0.0.1:6379->6379/tcp")[0][0] == "127.0.0.1"
    ports = security.parse_docker_ps(fx("docker_ps.jsonl"))
    exp = [p for p in ports if p.exposed]
    assert [(p.container, p.host_port) for p in exp] == [("shop-db-1", "5432"), ("web", "8080")]
    assert exp[0].compose_dir == "/home/infinite4evr/code/shop" and exp[0].compose_service == "db"
    assert any(p.container == "cache" and not p.exposed for p in ports)


def test_docker_check_levels():
    ports = security.parse_docker_ps(fx("docker_ps.jsonl"))
    fw_on = security.Check("firewall", "Firewall", "ok", "On")
    c = security.docker_check(fw_on, ("ok", ports))
    assert c.level == "bad" and "does NOT block" in c.detail and "PostgreSQL" in c.detail
    assert c.steps[0].root and c.steps[0].cmd[:2] == ["python3", "-c"] and c.steps[0].cmd[-2:] == ["/etc/docker/daemon.json", "127.0.0.1"]
    only_web = [p for p in ports if p.container == "web"]
    assert security.docker_check(None, ("ok", only_web)).level == "warn"
    assert security.docker_check(fw_on, ("missing", [])) is None
    assert security.docker_check(fw_on, ("not-running", [])).level == "ok"
    assert security.docker_check(fw_on, ("ok", [p for p in ports if p.container == "cache"])).level == "ok"
    text = security.docker_fix_text(ports)
    assert '"127.0.0.1:5432:5432"' in text and "cd /home/infinite4evr/code/shop && docker compose up -d" in text
    assert "-p 127.0.0.1:8080:3000" in text


def test_docker_daemon_script(tmp_path):
    p = tmp_path / "docker/daemon.json"
    subprocess.run(["python3", "-c", security.DAEMON_SET, str(p), "127.0.0.1"], check=True, capture_output=True)
    assert '"ip": "127.0.0.1"' in p.read_text()
    p.write_text('{"log-driver": "local", "ip": "127.0.0.1"}')
    subprocess.run(["python3", "-c", security.DAEMON_SET, str(p), ""], check=True, capture_output=True)
    assert '"ip"' not in p.read_text() and "log-driver" in p.read_text()
    p.write_text("{broken")
    r = subprocess.run(["python3", "-c", security.DAEMON_SET, str(p), "127.0.0.1"], capture_output=True, text=True)
    assert r.returncode != 0 and p.read_text() == "{broken"


# ---------------------------------------------------------------- SSH server

def test_parse_sshd_config_first_value_wins():
    files = {"/etc/ssh/sshd_config": fx("sshd_config"),
             "/etc/ssh/sshd_config.d/50-cloud-init.conf": fx("sshd_config.d/50-cloud-init.conf"),
             "/etc/ssh/sshd_config.d/60-custom.conf": fx("sshd_config.d/60-custom.conf")}
    s = security.parse_sshd_config("/etc/ssh/sshd_config", reader=lambda p: files.get(p, ""),
                                   globber=lambda pat: [k for k in files if k.startswith("/etc/ssh/sshd_config.d/")])
    assert s["passwordauthentication"] == "yes"     # the drop-in beats the main file
    assert s["permitrootlogin"] == "no"
    assert s["port"] == "2222" and s["usepam"] == "yes"
    items = {c.id: c for c in security.ssh_hardening({**security.SSHD_DEFAULTS, **s})}
    assert items["ssh-password"].level == "warn" and items["ssh-root"].level == "ok" and "Not the standard" in items["ssh-port"].detail


def test_parse_sshd_T_and_checks():
    s = security.parse_sshd_T(fx("sshd_T.txt"))
    assert s["permitrootlogin"] == "without-password" and s["port"] == "22"
    items = {c.id: c for c in security.ssh_hardening(s)}
    assert items["ssh-password"].level == "warn"
    assert items["ssh-root"].level == "ok"
    bad = {c.id: c for c in security.ssh_hardening({**s, "permitrootlogin": "yes", "permitemptypasswords": "yes", "passwordauthentication": "no"})}
    assert bad["ssh-root"].level == "bad" and bad["ssh-empty"].level == "bad" and bad["ssh-password"].level == "ok"


def test_ssh_harden_steps_depend_on_keys():
    with_keys = security.ssh_harden_steps(keys=2)
    content = with_keys[0].cmd[-1]
    assert with_keys[0].root and with_keys[0].cmd[-2] == security.HARDEN_FILE and security.HARDEN_FILE.endswith("00-pc-hardening.conf")
    assert "PasswordAuthentication no" in content and "PermitRootLogin no" in content
    assert "sshd -t" in with_keys[0].cmd[2]
    assert with_keys[1].cmd == ["systemctl", "try-reload-or-restart", "ssh.service"] and with_keys[1].optional
    no_keys = security.ssh_harden_steps(keys=0)[0].cmd[-1]
    assert "PasswordAuthentication" not in no_keys and "PermitRootLogin no" in no_keys


def test_parse_last_remote():
    rem = security.parse_last_remote(fx("last_ip.txt"))
    assert [(r["user"], r["from"]) for r in rem] == [("dev", "192.168.1.20"), ("root", "2001:db8::7")]
    assert rem[0]["when"].startswith("Tue Sep 23 18:00")


# ---------------------------------------------------------------- AppArmor

def test_apparmor_parsers():
    assert security.parse_aa_profiles(fx("aa_profiles.txt")) == {"enforce": 5, "unconfined": 2, "complain": 1}
    assert security.parse_aa_status(fx("aa_status.txt")) == {"enforce": 52, "complain": 4, "prompt": 0, "kill": 0, "unconfined": 64}
    assert security.parse_aa_status(fx("aa_status.json")) == {"enforce": 2, "unconfined": 1, "complain": 1}


def test_apparmor_check_levels():
    base = {"enabled": True, "counts": {"enforce": 52, "complain": 4}, "source": "kernel", "boot_off": False, "installed": True}
    assert security.apparmor(base).level == "ok" and "52" in security.apparmor(base).detail
    assert security.apparmor({**base, "counts": {}}).level == "ok"
    none_loaded = security.apparmor({**base, "counts": {"unconfined": 3}})
    assert none_loaded.level == "warn" and none_loaded.steps[0].cmd == ["systemctl", "enable", "--now", "apparmor.service"]
    assert security.apparmor({**base, "enabled": False}).level == "warn"
    assert "startup" in security.apparmor({**base, "enabled": False, "boot_off": True}).detail
    assert security.apparmor({**base, "enabled": None}).level == "info"


# ---------------------------------------------------------------- accounts

def test_accounts_build():
    shadow = accounts.parse_shadow(fx("shadow"))
    logins = accounts.parse_lastlog(fx("lastlog.txt"))
    accts = accounts.build(fx("passwd"), fx("group"), "infinite4evr", shadow, logins)
    names = [a.name for a in accts]
    assert names == ["infinite4evr", "guest", "dev", "root"]          # me first, root last; no system/nologin accounts
    me = accts[0]
    assert me.me and me.admin and me.password == "set" and me.last_login == "Wed Sep 24 09:12 2026" and "Docker" in me.rootish
    guest = accts[1]
    assert not guest.admin and guest.password == "none" and guest.last_login == "Never" and guest.rootish == ["Docker"]
    dev = accts[2]
    assert dev.admin and dev.password == "locked" and dev.last_from == "192.168.1.20"
    assert accts[3].uid == 0 and accts[3].password == "locked"
    warns = accounts.checks(accts)
    titles = [t for _l, t, _d in warns]
    assert "guest has no password" in titles and "2 accounts are admins" in titles and "guest has hidden admin power" in titles
    assert not any(t.startswith("infinite4evr has hidden") for t in titles)   # already an admin


def test_accounts_last_and_passwd_status():
    last = accounts.parse_last(fx("last.txt"))
    assert last["infinite4evr"] == ("Wed Sep 24 09:12", "") and last["dev"] == ("Tue Sep 23 18:00", "192.168.1.20")
    assert "reboot" not in last
    assert accounts.parse_passwd_status("infinite4evr P 09/01/2026 0 99999 7 -1") == "set"
    assert accounts.parse_passwd_status("guest NP 2026-09-01 0 99999 7 -1") == "none"
    assert accounts.parse_passwd_status("x L 2026-09-01") == "locked"
    assert accounts.parse_passwd_status("") == ""


# ---------------------------------------------------------------- ClamAV

def test_clamav_parsers():
    v = antivirus.parse_version("ClamAV 1.4.3/27771/Wed Sep 24 08:25:03 2026\n")
    assert v["engine"] == "1.4.3" and v["db"] == 27771 and v["date"] > 1.7e9
    assert antivirus.parse_version("ClamAV 1.0.5")["db"] == 0
    assert antivirus.parse_version("garbage")["engine"] == ""
    found = antivirus.parse_scan(fx("clamscan.log"))
    assert found == [{"path": "/home/infinite4evr/Downloads/eicar.com", "virus": "Win.Test.EICAR_HDB-1"},
                     {"path": "/home/infinite4evr/Downloads/odd: name.zip", "virus": "Win.Trojan.Agent-123"}]
    last = antivirus.last_scan(fx("clamscan.log"))
    assert last["folder"] == "/home/infinite4evr/Downloads" and last["finished"] == 1727000100 and len(last["found"]) == 2
    assert last["infected"] == []            # those files don't exist here
    assert antivirus.last_scan("") is None


def test_clamav_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(antivirus._run, "HOME", tmp_path)
    steps = antivirus.scan_steps("/home/u/Downloads")
    scan = steps[1]
    assert scan.cmd[:4] == ["clamscan", "-r", "-i", "--no-summary"] and scan.cmd[-1] == "/home/u/Downloads" and scan.ok_codes == (0, 1)
    assert scan.cmd[4] == f"--log={tmp_path}/.cache/pc/clamscan.log" and not scan.root
    steps[0]._func()
    (tmp_path / ".cache/pc/clamscan.log").open("a").write("/home/u/Downloads/x.exe: Win.Trojan.X FOUND\n")
    assert "1 infected file" in steps[2]._func()
    last = antivirus.last_scan()
    assert last["folder"] == "/home/u/Downloads" and last["finished"]
    t = antivirus.trash_steps(["/a b/x.exe"])[0]
    assert t.cmd == ["gio", "trash", "--", "/a b/x.exe"] and not t.root
    assert antivirus.install_steps()[0].cmd[-2:] == ["clamav", "clamav-freshclam"]
    assert [s.cmd[0] for s in antivirus.update_db_steps()] == ["systemctl", "freshclam", "systemctl"]


# ---------------------------------------------------------------- developer telemetry

def test_jsonc_set_keeps_comments():
    text = fx("vscode_settings.jsonc")
    new = devtelemetry.jsonc_set(text, "telemetry.telemetryLevel", "off")
    assert "// my editor settings" in new and "/* \"telemetry.telemetryLevel\": \"all\", */" in new   # comment untouched
    assert devtelemetry.load_jsonc(new)["telemetry.telemetryLevel"] == "off"
    assert devtelemetry.load_jsonc(new)["editor.fontSize"] == 14
    again = devtelemetry.jsonc_set(new, "telemetry.telemetryLevel", "off")
    assert again.count('"telemetry.telemetryLevel": "off"') == 1
    back = devtelemetry.jsonc_remove(new, "telemetry.telemetryLevel")
    assert "telemetry.telemetryLevel\": \"off\"" not in back and devtelemetry.load_jsonc(back)["editor.fontSize"] == 14
    assert "// my editor settings" in back


def test_jsonc_strict_and_empty_and_broken():
    assert devtelemetry.load_jsonc(devtelemetry.jsonc_set('{"a": 1}', "telemetry.telemetryLevel", "off")) == {"a": 1, "telemetry.telemetryLevel": "off"}
    assert devtelemetry.load_jsonc(devtelemetry.jsonc_set("", "k", "off")) == {"k": "off"}
    assert devtelemetry.load_jsonc(devtelemetry.jsonc_set("// c\n{}", "k", "off")) == {"k": "off"}
    assert devtelemetry.jsonc_set("{ this is not json", "k", "off") is None
    assert devtelemetry.jsonc_remove('{"a": 1}', "k") == '{"a": 1}'


def test_block_add_remove_roundtrip():
    original = "# my bashrc\nalias ll='ls -la'\n"
    added = devtelemetry.add_block(original)
    assert added.startswith(original) and devtelemetry.BEGIN in added and "export NEXT_TELEMETRY_DISABLED=1" in added
    assert devtelemetry.add_block(added).count(devtelemetry.BEGIN) == 1
    assert devtelemetry.remove_block(added) == original


def test_vars_are_unique_and_known():
    names = [v.name for v in devtelemetry.VARS]
    assert len(names) == len(set(names))
    for must in ("NEXT_TELEMETRY_DISABLED", "DOTNET_CLI_TELEMETRY_OPTOUT", "HOMEBREW_NO_ANALYTICS", "NG_CLI_ANALYTICS", "DO_NOT_TRACK",
                 "AZURE_CORE_COLLECT_TELEMETRY", "STORYBOOK_DISABLE_TELEMETRY", "TURBO_TELEMETRY_DISABLED", "NETLIFY_TELEMETRY_DISABLED"):
        assert must in names


def test_telemetry_off_on_in_fake_home(tmp_path):
    home = tmp_path
    (home / ".bashrc").write_text("# bashrc\n")
    (home / ".zshrc").write_text("")
    (home / ".config/fish").mkdir(parents=True)
    settings = home / ".config/Code/User/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(fx("vscode_settings.jsonc"))
    st = devtelemetry.status(home, env={})
    assert not st["configured"] and st["off_count"] == 0 and st["editors"][0]["level"] == "all"
    steps = devtelemetry.off_steps(home)
    assert all(s.cmd[0] == "__python__" for s in steps)      # only your own files, no admin rights
    for s in steps:
        s._func()
    envf = (home / devtelemetry.ENV_REL).read_text()
    assert "NEXT_TELEMETRY_DISABLED=1" in envf and "export" not in envf
    assert devtelemetry.BEGIN in (home / ".bashrc").read_text() and devtelemetry.BEGIN in (home / ".zshenv").read_text()
    assert "set -gx DOTNET_CLI_TELEMETRY_OPTOUT 1" in (home / devtelemetry.FISH_REL).read_text()
    assert devtelemetry.load_jsonc(settings.read_text())["telemetry.telemetryLevel"] == "off"
    assert (settings.parent / "settings.json.pc-backup").exists()
    st = devtelemetry.status(home, env={})
    assert st["configured"] and st["off_count"] == st["total"]
    for s in devtelemetry.on_steps(home):
        s._func()
    assert not (home / devtelemetry.ENV_REL).exists() and not (home / devtelemetry.FISH_REL).exists()
    assert (home / ".bashrc").read_text() == "# bashrc\n"
    assert "telemetry.telemetryLevel\": \"off\"" not in settings.read_text()
    assert "// my editor settings" in settings.read_text()


# ---------------------------------------------------------------- file search indexing

def test_indexing_strv():
    assert indexing.parse_strv("['&DESKTOP', '&DOCUMENTS', '$HOME']") == ["&DESKTOP", "&DOCUMENTS", "$HOME"]
    assert indexing.parse_strv("@as []") == []
    assert indexing.parse_strv("['/home/u/it\\'s here']") == ["/home/u/it's here"]
    assert indexing.strv(["&DESKTOP", "/home/u/it's"]) == "['&DESKTOP', '/home/u/it\\'s']"
    assert indexing.pretty_dirs(["&DOWNLOAD", "$HOME", "/home/u/code"], Path("/home/u")) == ["Downloads", "Home folder (top level only)", "~/code"]


def test_indexing_steps(tmp_path):
    st = {"cmd": "localsearch", "unit": "localsearch-3.service", "recursive": ["&DOCUMENTS"], "single": ["$HOME"], "masked": False, "enabled": True}
    off = indexing.off_steps(st, tmp_path)
    assert off[0].cmd[0] == "__python__"
    assert off[1].cmd == ["gsettings", "set", indexing.SCHEMA, "index-recursive-directories", "[]"]
    assert off[3].cmd == ["systemctl", "--user", "stop", "localsearch-3.service"] and off[3].optional
    off[0]._func()
    on = indexing.on_steps({**st, "recursive": [], "single": [], "masked": True, "enabled": False}, tmp_path)
    assert on[0].cmd == ["systemctl", "--user", "unmask", "localsearch-3.service"]
    assert on[1].cmd[-1] == "['&DOCUMENTS']" and on[2].cmd[-1] == "['$HOME']"
    fresh = indexing.on_steps({**st, "masked": False}, tmp_path / "nowhere")
    assert fresh[0].cmd == ["gsettings", "reset", indexing.SCHEMA, "index-recursive-directories"]
    reset = indexing.reset_steps(st)
    assert reset[0].cmd == ["bash", "-c", "echo y | localsearch reset -s"] and reset[-1].cmd[-1] == "localsearch-3.service"
    assert indexing.reset_steps({**st, "cmd": "tracker3", "enabled": False})[0].cmd[-1] == "echo y | tracker3 reset -s"
    assert indexing.block_steps(st)[0].cmd == ["systemctl", "--user", "mask", "--now", "localsearch-3.service"]
    assert indexing.block_steps({**st, "unit": ""}) == []


# ---------------------------------------------------------------- old public names keep working

def test_public_names_kept():
    from pcctl.core import privacy
    c = security.Check("id", "t", "ok", "d", "fix", [], goto="x")
    assert c.goto == "x"
    assert all(hasattr(s, "title") for s in privacy.SETTINGS)
    for name in ("all_checks", "score", "firewall", "ssh", "exposed_ports", "parse_ufw_rules", "ufw_allow_steps", "ufw_delete_step", "auto_updates"):
        assert callable(getattr(security, name))
