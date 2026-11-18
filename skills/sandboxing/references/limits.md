# Limits of the sandbox

## Threat model

The program inside is **cooperative**: a nested agent or test harness that
is not trying to escape. The sandbox stops two kinds of harm:

1. **Secrets reaching an inference provider.** The program can't read the
   caller's environment, other processes' `/proc/*/environ` or `cmdline`,
   the caller's home or credential folders, so it can't paste an API key or
   session token into a prompt.
2. **Bumbling damage.** A wrong `rm -rf` or a stray edit can touch only
   `/work` and the `--rw` binds.

`scripts/leak_test.py` checks harm 1 on the machine at hand: it plants a
random marker in an environment variable, another process's environment
and command line, and a mode-600 file, then looks for it from inside
(`env`, `/proc`, the file, `grep -r` over `/`). Run it once per machine or
container image; exit 0 and `PASS` means none of those leaked.

## What it does not protect

- **Anything you bind or pass in.** `--ro`, `--rw`, `--pass-env` and
  `--setenv` values are readable inside. A real key passed with
  `--pass-env` is as exposed as without a sandbox.
- **The network.** By default the network is shared. Whatever the program
  can read it can send to any host the proxy (or the network) allows,
  including the inference provider it talks to. `--no-net` removes the
  network entirely; there is no host allowlist here: filtering is the
  proxy's job.
- **Kernel and bwrap bugs.** A user-namespace sandbox shares the host
  kernel; a kernel exploit escapes it.
- **Syscalls.** No seccomp filter: every syscall the kernel allows an
  unprivileged user is allowed.
- **Resources by default.** Without `--mem`, `--nproc` and `--cpu`, a fork
  bomb or a runaway allocation hits the host. The limits are per process
  (prlimit), not a cgroup: no total memory or disk quota, and `/work` and
  `/tmp` can fill the disk.
- **Shared files under `/usr`.** `/usr` is read-only but readable: anything
  secret stored there is visible.
- **Timing.** No wall-clock limit; wrap the call in `timeout`.

## Stronger tools, by need

| Need | Tool |
|-|-|
| Syscall filtering, cgroup limits, still lightweight | nsjail (with a seccomp policy), firejail |
| Untrusted or adversarial code on a shared host | gVisor (`runsc`), a separate user-namespace container with seccomp |
| A model told to escape, malware | a microVM (Firecracker, Kata Containers, a throwaway cloud VM) |
| Outbound filtering | an egress proxy with a host allowlist, in front of any of the above |
