# Synthetic proxy-health incident

Use the proxy fragment and trace in `snapshots/` as the complete evidence set.
Create `proxy-fixed.conf` and `diagnosis.json`. The result is checked by a local
parser and must never be applied to, or contact, a real proxy or endpoint.
