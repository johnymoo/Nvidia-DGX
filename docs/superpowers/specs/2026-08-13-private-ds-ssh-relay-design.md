# Private DS SSH Relay Design

Date: 2026-08-13 (Asia/Shanghai)  
Status: approved design pending final rendered-hash confirmation  
Baseline: `private-ds-ssh-relay-r1`

## Authority And Evidence

- User request: expose the running Private DS API through an SSH tunnel using
  `vps-tencent-tokyo` as relay.
- Baseline approval: user confirmed the SSH-only relay on 2026-08-13 and
  approved the detailed design in this task.
- Repository base: `5e4f2408b304f21995359ed5637e9b7ccc432bb5`.
- Client key source: ignored workspace `.env`, variable `SSH_PUB_KEY`. The
  design records only ED25519 fingerprint
  `SHA256:aYpMHYmSrHCM4kMFUek2yf7A/th4JlRpk2prLeo4Xxs`; the public key body is
  not stored in tracked artifacts.
- Live relay: `vps-tencent-tokyo` resolves through SSH config to
  `chriswang@43.167.173.46:36392`. OpenSSH permits TCP forwarding and has
  `GatewayPorts=no`. UFW currently exposes SSH, HTTP/HTTPS, and unrelated
  existing services; no relay API port is open.
- Live API: `gb10` serves `deepseek-v4-flash-0731` on `0.0.0.0:8890`; the
  production service controller reports both ranks healthy.

## Approved User Stories

### `DS-TUNNEL-01`

As an external developer, I want to use the public key from `.env` to create
an SSH local forward through `vps-tencent-tokyo`, so that I can access Private
DS without exposing the API itself on a public port.

Given the reverse tunnel is healthy and the client has the approved private
key, when the client connects to the VPS SSH port and requests the one allowed
local forward, then `http://127.0.0.1:8890/v1` reaches the private
`deepseek-v4-flash-0731` API.

### `DS-TUNNEL-02`

As an operator, I want the GB10-to-VPS reverse tunnel to start automatically,
reconnect after interruption, and expose status and stop controls, so that the
relay remains operable without changing the inference service lifecycle.

Given Private DS is healthy, when the GB10 user service starts or reconnects,
then the VPS loopback listener returns without restarting or modifying
DeepSeek. When the service is stopped, the listener disappears and DeepSeek
remains healthy.

### `DS-TUNNEL-03`

As a security owner, I want each SSH key to have one narrowly scoped forwarding
capability and no interactive login, so that key compromise cannot grant a VPS
shell or arbitrary network access.

Given either restricted key is used, when it requests a shell, PTY, agent/X11
forwarding, user rc, or an unapproved destination/listener, then SSH rejects
the request. The client key may open only the approved DS relay path.

## Constraints And Non-Goals

- Do not expose `8890`, `18890`, or another DS API port through VPS public
  interfaces, UFW, Nginx, or a cloud firewall rule.
- Do not add HTTP authentication, TLS termination, a domain, a public API
  gateway, or non-SSH client support.
- Do not change the DeepSeek Compose profile, `:8890` model service, Qwen
  `:8004` proxy, trading, lexdata, or other protected workloads.
- Do not store private keys, tokens, passwords, or public-key bodies in Git.
- Do not reuse personal SSH keys for the GB10 service tunnel.

## Architecture

The design uses two independent restricted VPS accounts.

1. `ds-tunnel` authenticates a new GB10-generated ED25519 key. Its key entry
   permits remote listening only at `127.0.0.1:18890` and disables shell,
   PTY, agent forwarding, X11 forwarding, and user rc processing.
2. `ds-client` authenticates the `.env` public key fingerprint listed above.
   Its key entry permits forwarding only to `127.0.0.1:18890` and applies the
   same non-interactive restrictions.
3. A `gb10` user-level systemd service runs OpenSSH with
   `-R 127.0.0.1:18890:127.0.0.1:8890`, `ExitOnForwardFailure=yes`, server
   keepalives, host-key pinning, and automatic restart.
4. An external workstation connects to VPS SSH port `36392` and requests
   `-L 8890:127.0.0.1:18890`. Its local `127.0.0.1:8890` becomes the only
   external API access point.

`GatewayPorts=no` and the explicit loopback bind are both required. The VPS
must show no public listener for `18890` before acceptance.

## VPS Access Controls

Create system users with locked passwords, dedicated homes, and no sudo or
supplementary groups. Use `/usr/sbin/nologin` only if forwarding is proven to
work with the installed OpenSSH behavior; otherwise retain a shell in passwd
and enforce non-interactive behavior through authorized-key restrictions and
an sshd `Match User` block.

The sshd drop-in must use fail-closed account blocks:

- `PasswordAuthentication no`
- `KbdInteractiveAuthentication no`
- `AllowAgentForwarding no`
- `X11Forwarding no`
- `PermitTTY no`
- `PermitUserRC no`
- `AllowTcpForwarding remote` for `ds-tunnel`
- `AllowTcpForwarding local` for `ds-client`

The `ds-tunnel` authorized key uses `restrict`,
`permitlisten="127.0.0.1:18890"`, and an inert forced command. The `ds-client`
key uses `restrict`, `permitopen="127.0.0.1:18890"`, and an inert forced
command. Implementation must validate the exact syntax against the VPS
OpenSSH version with `sshd -t` before reload. Existing SSH access on port
`36392` must be tested in a second connection before closing the first admin
session.

No UFW or cloud firewall change is part of this delivery.

## GB10 Service

Generate a dedicated key under a project-specific private directory outside
Git, mode `0700`, with private key mode `0600`. Copy only its public key to the
restricted VPS account. Add the VPS host key to a dedicated known-hosts file
after comparing it with the key obtained through the already trusted SSH
connection.

Install a user unit such as `private-ds-vps-tunnel.service` under
`~/.config/systemd/user/`. The unit depends on network availability but not on
the DeepSeek container. Its command runs only `/usr/bin/ssh -NT` with:

- `BatchMode=yes`
- `ExitOnForwardFailure=yes`
- `ServerAliveInterval=30`
- `ServerAliveCountMax=3`
- `StrictHostKeyChecking=yes`
- dedicated identity and known-hosts files
- VPS SSH port `36392`
- the exact reverse-forward mapping

Use `Restart=always` with a bounded delay. Existing user linger is already
enabled, so the unit can survive logout. Tunnel failure must never stop,
restart, or mutate DeepSeek.

## Client Workflow

The operator provides this connection shape to the key holder without
distributing any additional secret:

```bash
ssh -NT \
  -p 36392 \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:8890:127.0.0.1:18890 \
  ds-client@43.167.173.46
```

The client then points OpenAI-compatible tools to
`http://127.0.0.1:8890/v1`. If local port `8890` is occupied, the client may
change only the left-hand local port; the VPS destination remains fixed.

## Failure Handling And Recovery

- If VPS account or sshd validation fails, make no GB10 service change.
- If sshd reload fails or a second admin SSH connection cannot be established,
  restore the captured sshd configuration immediately and revalidate.
- If the GB10 service cannot establish the reverse listener, keep DeepSeek
  running, preserve journal evidence, and leave the service failed/retrying.
- If `18890` is already occupied, stop and investigate ownership; do not select
  another port silently.
- If the external API test fails, inspect each hop independently: DeepSeek
  loopback, VPS loopback, then client loopback.

Rollback order is: stop and disable the GB10 user unit; verify VPS `18890` is
closed; remove the dedicated GB10 key and known-hosts file; remove the VPS
restricted account keys and sshd drop-in; validate and reload sshd; remove the
two dedicated users only after confirming no owned processes remain. Existing
admin SSH and all model services remain in place.

## Verification

Acceptance requires fresh evidence for all of the following:

1. VPS `ss` shows `127.0.0.1:18890` only, with no `0.0.0.0`, public-address,
   or IPv6 wildcard listener.
2. A scan of the VPS public address does not expose `18890` or `8890`, and UFW
   rules are unchanged.
3. The approved client key establishes the documented local forward.
4. Through client loopback, `/v1/models` returns only
   `deepseek-v4-flash-0731`, and a deterministic completion succeeds.
5. Shell, PTY, remote forwarding from `ds-client`, local forwarding from
   `ds-tunnel`, and forwarding to unrelated VPS ports are rejected.
6. Killing the tunnel SSH process causes systemd to reconnect and restore the
   same loopback listener.
7. Stopping the tunnel removes the relay listener while DeepSeek remains
   `running`; restarting restores access.
8. Qwen `http://192.168.88.181:8004/v1/models` and protected service health are
   unchanged.

## Story Playback

| Story | Design coverage | Status |
| --- | --- | --- |
| `DS-TUNNEL-01` | Client key, SSH local forward, loopback API, identity and completion tests | Covered |
| `DS-TUNNEL-02` | Dedicated systemd user unit, restart policy, status/stop/recovery tests | Covered |
| `DS-TUNNEL-03` | Separate accounts, key options, sshd Match blocks, negative access tests | Covered |

Design drift score: `0`. The design adds no public API listener and does not
change any approved model or protected service contract.

## Implementation Boundary

Allowed subjects are the two VPS restricted users and their SSH configuration,
the GB10 dedicated tunnel key/known-hosts/user unit, a secret-free project
operations script or template if needed, and the core operations runbook.
Existing SSH configuration must be extended with a new validated drop-in, not
rewritten. Existing model Compose files, model containers, firewall rules, and
unrelated accounts are excluded.

