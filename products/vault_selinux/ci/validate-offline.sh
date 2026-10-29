#!/usr/bin/env bash
# Run only inside a disposable Mock root, never on a live SELinux host.
set -euo pipefail
if selinuxenabled; then
    echo 'Refusing to modify a live SELinux policy store' >&2
    exit 1
fi
if [ -e /sys/fs/selinux/enforce ] && ! findmnt -n -o OPTIONS -T /sys/fs/selinux/enforce | grep -Eq '(^|,)ro(,|$)'; then
    echo 'Refusing a writable kernel SELinux filesystem' >&2
    exit 1
fi
if [ "$#" -ne 2 ]; then
    echo 'Usage: validate-offline.sh LEGACY_RPM CANDIDATE_RPM' >&2
    exit 1
fi
legacy=$1
candidate=$2
port_is_ours() {
    semanage port -l -C | awk '$1 == "vault_cluster_port_t" && $2 == "tcp" { for (i=3; i<=NF; i++) { gsub(/,/, "", $i); if ($i == "8201") found=1 } } END { exit !found }'
}
module_exists() { semodule -l | grep -E '^vault([[:space:]].*)?$' > /dev/null; }
assert_policy() {
    local policy result
    policy=$(find /etc/selinux/targeted/policy -name 'policy.*' | sort -V | tail -1)
    test -n "$policy"
    test -n "$(sesearch --allow -s vault_t -t vault_sys_content_t -c file -p write "$policy")"
    test -n "$(sesearch --allow -s vault_t -t vault_sys_content_t -c dir -p rmdir "$policy")"
    result=$(sesearch --allow -s vault_t -t vault_conf_t -c file -p write "$policy")
    test -z "$result"
    result=$(sesearch --allow -s vault_t -t vault_conf_t -c dir -p remove_name "$policy")
    test -z "$result"
    result=$(sesearch --allow -s vault_t -t vault_root_t -c dir -p remove_name "$policy")
    test -z "$result"
    result=$(sesearch --allow -s vault_t -t unreserved_port_t -c tcp_socket -p name_connect "$policy")
    test -z "$result"
    result=$(sesearch --allow -s vault_t -t bin_t -c file -p execute "$policy")
    test -z "$result"
    mkdir -p /opt/vault/data /opt/vault/tls /var/log/vault-unrelated
    matchpathcon -n /opt/vault | grep -q ':vault_root_t:'
    matchpathcon -n /opt/vault/data | grep -q ':vault_sys_content_t:'
    matchpathcon -n /opt/vault/tls | grep -q ':vault_conf_t:'
    if matchpathcon -n /var/log/vault-unrelated | grep -q ':vault_log_t:'; then exit 1; fi
}

# Fresh install and reinstall must leave the same policy and mapping.
rpm -Uvh "$candidate"
module_exists
port_is_ours
assert_policy
rpm -Uvh --replacepkgs "$candidate"
module_exists
port_is_ours
rpm -e vault_selinux
if module_exists || port_is_ours; then exit 1; fi

# Exercise the actual legacy preun, not just a simulated modern upgrade.
rpm -Uvh "$legacy"
port_is_ours
rpm -Uvh "$candidate"
module_exists
port_is_ours
assert_policy
rpm -e vault_selinux
if module_exists || port_is_ours; then exit 1; fi

# Never take over or delete an administrator's conflicting local mapping.
semanage port -a -t http_port_t -p tcp 8201
if rpm -Uvh "$candidate" > /tmp/vault-policy-conflict.log 2>&1; then exit 1; fi
grep -q 'Conflicting local TCP 8201 mapping' /tmp/vault-policy-conflict.log
if port_is_ours; then exit 1; fi
semanage port -l -C | grep '^http_port_t' | grep -q '8201'
if rpm -q vault_selinux; then exit 1; fi
semanage port -l -C | grep '^http_port_t' | grep -q '8201'
semanage port -d -p tcp 8201

# A rejected legacy upgrade must retain both the old RPM and local mapping.
rpm -Uvh "$legacy"
semanage port -m -t http_port_t -p tcp 8201
if rpm -Uvh "$candidate" > /tmp/vault-policy-legacy-conflict.log 2>&1; then exit 1; fi
grep -q 'Conflicting local TCP 8201 mapping' /tmp/vault-policy-legacy-conflict.log
test "$(rpm -q --qf '%{VERSION}' vault_selinux)" = 0.1.7
semanage port -l -C | grep '^http_port_t' | grep -q '8201'
# Restore ownership before removing the legacy package with its unsafe preun.
semanage port -m -t vault_cluster_port_t -p tcp 8201
rpm -e vault_selinux
if module_exists || port_is_ours; then exit 1; fi
echo 'Offline install/reinstall/legacy-upgrade/removal/conflict and policy assertions passed'
echo 'This does not establish runtime domain transition or enforcing Vault operation.'
