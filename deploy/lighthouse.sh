#!/usr/bin/env bash
# Tencent Cloud Lighthouse (Singapore) operations for the public demo, all via tccli.
# Credentials: TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY in the environment;
# they are never passed on a command line. Usage:
#   deploy/lighthouse.sh status                 # instances, key pairs, balance
#   deploy/lighthouse.sh create [--dry-run]     # buy the instance (5.60 USD/month prepaid, no auto-renew)
#   deploy/lighthouse.sh wait                   # block until RUNNING, print public IP
#   deploy/lighthouse.sh firewall               # 80/443 open to all, 22 only from this machine
#   deploy/lighthouse.sh ssh [cmd]              # ssh into the instance
#   deploy/lighthouse.sh teardown               # terminate instance + delete key pair
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
TC=${TCCLI:-tccli}
[ -x "$TC" ] || { echo "tccli not found; pip install tccli or set TCCLI"; exit 2; }
export TENCENTCLOUD_REGION=${TENCENTCLOUD_REGION:-ap-singapore}
ZONE=${ZONE:-ap-singapore-3}
BUNDLE=${BUNDLE:-bundle_rs_nmc_lin_med2_01}      # Razor Speed 2C/2G/40GB/200Mbps, unlimited traffic, 5.60 USD/month
BLUEPRINT=${BLUEPRINT:-lhbp-b46k6f98}           # application image "Docker" on Ubuntu 24.04 (NOT lhbp-7wrz1nyu, which is "Hermes Agent")
NAME=${NAME:-akina-court}
KEYNAME=${KEYNAME:-akina_court}
PRIV=$HOME/.ssh/$KEYNAME
SSH_USER=${SSH_USER:-ubuntu}
[ -n "${TENCENTCLOUD_SECRET_ID:-}" ] || { echo "TENCENTCLOUD_SECRET_ID not set"; exit 2; }

py() { python3 -c "$1"; }
instance_json() { $TC lighthouse DescribeInstances --Filters "[{\"Name\":\"instance-name\",\"Values\":[\"$NAME\"]}]"; }
instance_id() { instance_json | py 'import json,sys;d=json.load(sys.stdin);s=d["InstanceSet"];print(s[0]["InstanceId"] if s else "")'; }
instance_ip() { instance_json | py 'import json,sys;d=json.load(sys.stdin);s=d["InstanceSet"];print((s[0].get("PublicAddresses") or [""])[0] if s else "")'; }
key_id() { $TC lighthouse DescribeKeyPairs --Filters "[{\"Name\":\"key-name\",\"Values\":[\"$KEYNAME\"]}]" | py 'import json,sys;d=json.load(sys.stdin);s=d["KeyPairSet"];print(s[0]["KeyId"] if s else "")'; }

cmd=${1:-status}; shift || true
case "$cmd" in
  status)
    echo "== balance"; $TC billing DescribeAccountBalance | py 'import json,sys;d=json.load(sys.stdin);print("balance",d["Balance"],"credit",d.get("CreditAmount"))'
    echo "== key pair $KEYNAME: $(key_id)"
    echo "== instances"; instance_json | py 'import json,sys
for i in json.load(sys.stdin)["InstanceSet"]:
    print(i["InstanceId"],i["InstanceName"],i["InstanceState"],i["Zone"],i["BundleId"],"ip",i.get("PublicAddresses"),"expires",i.get("ExpiredTime"))' ;;
  price)
    $TC lighthouse InquirePriceCreateInstances --BundleId "$BUNDLE" --BlueprintId "$BLUEPRINT" --InstanceChargePrepaid '{"Period":1,"RenewFlag":"NOTIFY_AND_MANUAL_RENEW"}' --InstanceCount 1 | py 'import json,sys;p=json.load(sys.stdin)["Price"]["InstancePrice"];print(p["DiscountPrice"],p["Currency"],"per month")' ;;
  keypair)
    [ -n "$(key_id)" ] && { echo "key pair exists: $(key_id)"; exit 0; }
    umask 077; mkdir -p ~/.ssh
    $TC lighthouse CreateKeyPair --KeyName "$KEYNAME" | py "import json,sys,os
kp=json.load(sys.stdin)['KeyPair']; p=os.path.expanduser('$PRIV')
open(p,'w').write(kp['PrivateKey']); os.chmod(p,0o600); open(p+'.pub','w').write(kp['PublicKey']+'\n'); print('created',kp['KeyId'],'private key',p)" ;;
  create)
    KID=$(key_id); [ -n "$KID" ] || { echo "run: $0 keypair first"; exit 2; }
    [ -z "$(instance_id)" ] || { echo "instance already exists: $(instance_id)"; exit 0; }
    DRY=false; [ "${1:-}" = "--dry-run" ] && DRY=true
    echo "bundle=$BUNDLE blueprint=$BLUEPRINT zone=$ZONE key=$KID dry_run=$DRY price=$($0 price)"
    $TC lighthouse CreateInstances --BundleId "$BUNDLE" --BlueprintId "$BLUEPRINT" --InstanceChargePrepaid '{"Period":1,"RenewFlag":"NOTIFY_AND_MANUAL_RENEW"}' \
      --InstanceName "$NAME" --Zones "[\"$ZONE\"]" --LoginConfiguration "{\"KeyIds\":[\"$KID\"]}" --DryRun $DRY ;;
  wait)
    for i in $(seq 1 60); do
      st=$(instance_json | py 'import json,sys;s=json.load(sys.stdin)["InstanceSet"];print(s[0]["InstanceState"] if s else "NONE")')
      ip=$(instance_ip); echo "  $st ${ip:-}"; [ "$st" = RUNNING ] && [ -n "$ip" ] && { echo "IP $ip"; exit 0; }; sleep 5
    done; echo "timed out"; exit 1 ;;
  firewall)
    ID=$(instance_id); ME=$(curl -s https://api.ipify.org)
    echo "instance $ID, my ip $ME"
    $TC lighthouse DescribeFirewallRules --InstanceId "$ID" | py 'import json,sys
for r in json.load(sys.stdin)["FirewallRuleSet"]: print("  existing",r["Protocol"],r["Port"],r["CidrBlock"],r["Action"],r.get("FirewallRuleDescription"))'
    # replace the image's default rule set (80/443/22/3389 open to all) with ours
    $TC lighthouse ModifyFirewallRules --InstanceId "$ID" --FirewallRules "[{\"Protocol\":\"TCP\",\"Port\":\"80\",\"CidrBlock\":\"0.0.0.0/0\",\"Action\":\"ACCEPT\",\"FirewallRuleDescription\":\"http\"},{\"Protocol\":\"TCP\",\"Port\":\"443\",\"CidrBlock\":\"0.0.0.0/0\",\"Action\":\"ACCEPT\",\"FirewallRuleDescription\":\"https\"},{\"Protocol\":\"TCP\",\"Port\":\"22\",\"CidrBlock\":\"$ME/32\",\"Action\":\"ACCEPT\",\"FirewallRuleDescription\":\"ssh from dev machine\"},{\"Protocol\":\"ICMP\",\"Port\":\"ALL\",\"CidrBlock\":\"0.0.0.0/0\",\"Action\":\"ACCEPT\",\"FirewallRuleDescription\":\"ping\"}]" | py 'import json,sys;print("modified, request",json.load(sys.stdin)["RequestId"])'
    $TC lighthouse DescribeFirewallRules --InstanceId "$ID" | py 'import json,sys
for r in json.load(sys.stdin)["FirewallRuleSet"]: print("  now",r["Protocol"],r["Port"],r["CidrBlock"],r["Action"])' ;;
  ssh)
    IP=$(instance_ip); exec ssh -i "$PRIV" -o StrictHostKeyChecking=accept-new "$SSH_USER@$IP" "$@" ;;
  deploy)
    # ship the working tree (without .env, .venv, .git) and start the app + Caddy on the instance
    IP=$(instance_ip); S="ssh -i $PRIV -o StrictHostKeyChecking=accept-new"; DOM=${DOMAIN:-$IP.sslip.io}
    TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')
    # local-only files listed in .git/info/exclude (editor and tooling config) never leave this machine
    LOCAL_EXCL=(); [ -f "$HERE/../.git/info/exclude" ] && while read -r l; do case "$l" in ''|'#'*) ;; *) LOCAL_EXCL+=(--exclude "./${l%/}");; esac; done < "$HERE/../.git/info/exclude"
    COPYFILE_DISABLE=1 tar --no-xattrs --exclude .venv --exclude .env --exclude .git --exclude '__pycache__' --exclude '.pytest_cache' "${LOCAL_EXCL[@]}" -czf /tmp/akina.tgz -C "$HERE/.." .
    echo "bundle $(du -h /tmp/akina.tgz | cut -f1) → $SSH_USER@$IP (domain $DOM)"
    scp -i "$PRIV" /tmp/akina.tgz "$SSH_USER@$IP:akina.tgz"
    $S "$SSH_USER@$IP" "set -e; rm -rf akina && mkdir akina && tar -xzf akina.tgz -C akina && rm akina.tgz
      printf 'LIVE_RUNS=0\nDEMO_TOKEN=$TOKEN\nDOMAIN=$DOM\n' > akina/deploy/.env
      cd akina/deploy && sudo docker compose up -d --build --remove-orphans && sudo docker compose ps --format 'table {{.Name}}\t{{.Status}}'"
    echo "open: https://$DOM/" ;;
  teardown)
    ID=$(instance_id); [ -n "$ID" ] && $TC lighthouse TerminateInstances --InstanceIds "[\"$ID\"]"
    KID=$(key_id); [ -n "$KID" ] && $TC lighthouse DeleteKeyPairs --KeyIds "[\"$KID\"]"; echo done ;;
  *) echo "unknown: $cmd"; exit 2 ;;
esac
