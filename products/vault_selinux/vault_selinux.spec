# vim: sw=4:ts=4:et

%define cluster_port_is_ours semanage port -l -C | awk '$1 == "vault_cluster_port_t" && $2 == "tcp" { for (i = 3; i <= NF; i++) { gsub(/,/, "", $i); if ($i == "8201") found = 1 } } END { exit !found }'
%define cluster_port_is_locally_assigned semanage port -l -C | awk '$2 == "tcp" { for (i = 3; i <= NF; i++) { gsub(/,/, "", $i); n = split($i, p, "-"); if ((n == 1 && p[1] == 8201) || (n == 2 && p[1] <= 8201 && p[2] >= 8201)) found = 1 } } END { exit !found }'

Name:       vault_selinux
Version:    0.1.8
Release:    1%{?dist}
Summary:    SELinux policy module for Vault
License:    MPLv2
URL:        https://www.vaultproject.io/
Source0:    vault.fc
Source1:    vault.if
Source2:    vault.te
Source3:    vault_selinux.8
BuildArch:  noarch
BuildRequires: make, selinux-policy-devel
Requires: selinux-policy-targeted, policycoreutils, libselinux-utils
Requires(post): selinux-policy-targeted, policycoreutils, libselinux-utils
Requires(postun): policycoreutils, libselinux-utils
%if 0%{?rhel} == 7
Requires: policycoreutils-python
Requires(pre): policycoreutils-python
Requires(preun): policycoreutils-python
Requires(posttrans): policycoreutils-python
%else
Requires: policycoreutils-python-utils
Requires(pre): policycoreutils-python-utils
Requires(preun): policycoreutils-python-utils
Requires(posttrans): policycoreutils-python-utils
%endif

%description
SELinux confinement for Vault with separate writable Raft storage and
read-only configuration/TLS paths. External executable plugins require
an additional, explicitly scoped policy.

%prep
%setup -q -c -T
cp %{SOURCE0} %{SOURCE1} %{SOURCE2} .

%build
%{__make} -f /usr/share/selinux/devel/Makefile vault.pp

%install
install -D -m 644 vault.pp %{buildroot}%{_datadir}/selinux/packages/vault.pp
install -D -m 644 %{SOURCE1} %{buildroot}%{_datadir}/selinux/devel/include/contrib/vault.if
install -D -m 644 %{SOURCE3} %{buildroot}%{_mandir}/man8/vault_selinux.8

%pre
set -e
# Check before the legacy package can delete an administrator's mapping.
if ! %cluster_port_is_ours; then
    if %cluster_port_is_locally_assigned; then
        echo 'Conflicting local TCP 8201 mapping; refusing to replace it' >&2
        exit 1
    fi
fi

%post
set -e
semodule -n -i %{_datadir}/selinux/packages/vault.pp
if selinuxenabled; then
    load_policy
    # Also reset labels left by the old /var/log/vault(.*) context rule.
    # restorecon uses effective mappings, including administrator overrides.
    for path in /usr/bin/vault /etc/vault.d /opt/vault /var/log/vault*; do
        if [ -e "$path" ]; then restorecon -RF "$path"; fi
    done
fi

%posttrans
set -e
# Runs after the old 0.1.7 preun, which unconditionally deletes this mapping.
if ! %cluster_port_is_ours; then
    # semanage -a can silently modify an existing local record on EL10.
    if %cluster_port_is_locally_assigned; then
        echo 'Conflicting local TCP 8201 mapping; refusing to replace it' >&2
        exit 1
    fi
    semanage port -a -t vault_cluster_port_t -p tcp 8201
fi

%preun
set -e
if [ "$1" -eq 0 ]; then
    if %cluster_port_is_ours; then
        semanage port -d -p tcp 8201
    fi
fi

%postun
set -e
if [ "$1" -eq 0 ]; then
    semodule -n -r vault
    if selinuxenabled; then
        load_policy
        for path in /usr/bin/vault /etc/vault.d /opt/vault /var/log/vault*; do
            if [ -e "$path" ]; then restorecon -RF "$path"; fi
        done
    fi
fi

%files
%{_datadir}/selinux/packages/vault.pp
%{_datadir}/selinux/devel/include/contrib/vault.if
%{_mandir}/man8/vault_selinux.8.*

%changelog
* Thu Oct 29 2026 Local migration maintenance - 0.1.8-1
- Declare EL10 build/runtime dependencies and noarch packaging.
- Reconcile the owned cluster port after legacy upgrade scriptlets.
- Separate writable storage from TLS and its parent directory.
- Restrict log labels and remove generic command execution/outbound ports.

* Mon Nov 14 2022 Jan Prinsloo <jan.prinsloo@hashicorp.com> 0.1.6-1
- Added policycoreutils-python-utils requirement for Centos8/RHEL8

* Wed Jan 6 2021 Christian Frichot <cfrichot@hashicorp.com> 0.1.5-1
- Simplified local-package Makefile target

* Tue Nov 17 2020 Christian Frichot <cfrichot@hashicorp.com> 0.1.4-1
- Packaging for Centos7, Centos8, Fedora31, Fedora32, Fedora33

* Thu Nov 12 2020 Christian Frichot <cfrichot@hashicorp.com> 0.1.3-1
- Added booleans for outbound udp/dns and http

* Wed Sep 2 2020 Christian Frichot <cfrichot@hashicorp.com> 0.1.2-1
- Update for Hashicorp RPM Vault install

* Fri Aug 28 2020 Christian Frichot <cfrichot@hashicorp.com> 0.1.1-1
- Update to allow for outbound comms

* Wed Aug 12 2020 Christian Frichot <cfrichot@hashicorp.com> 0.1.0-1
- Initial version
