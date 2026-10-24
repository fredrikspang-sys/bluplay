#!/bin/sh
# Build all release artifacts for bluplay into dist/:
#   bluplay-VER.tar.gz                    source (git archive of tag vVER, top dir bluplay-VER/)
#   bluplay-VER-linux-x86_64.tar.gz       prebuilt binary + README/LICENSE
#   bluplay_VER_amd64.deb, bluplay-VER-1.x86_64.rpm   (nfpm)
#   bluplay-VER-x86_64-1_SBo.txz          Slackware package, built by slackbuild/bluplay/bluplay.SlackBuild
#   SHA256SUMS
#
# usage: scripts/release.sh [VERSION] [--ref GITREF] [--upload] [--no-slack]
#   VERSION defaults to BLUPLAY_VERSION in bluplay.c, GITREF to vVERSION.
#   --upload attaches the files to the existing GitHub release vVERSION (gh; never re-creates the tag).
# Needs: git, cc, make, gzip, xz, objdump, nfpm (https://nfpm.goreleaser.com), gh for --upload.
# The .txz needs root for the SlackBuild: run as root, or (non-root) via an unprivileged user namespace
# (unshare -r). Without /sbin/makepkg (or with MAKEPKG_LITE=1), scripts/makepkg-lite is used (CI).
set -eu
cd "$(dirname "$0")/.."
TOP=$(pwd)
VER=""; REF=""; UPLOAD=0; SLACK=1
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) REF=$2; shift ;;
    --upload) UPLOAD=1 ;;
    --no-slack) SLACK=0 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) VER=$1 ;;
  esac; shift
done
[ -n "$VER" ] || VER=$(sed -n 's/^#define BLUPLAY_VERSION "\(.*\)"/\1/p' bluplay.c)
[ -n "$REF" ] || REF=v$VER
NFPM=${NFPM:-nfpm}; command -v "$NFPM" >/dev/null || NFPM=$HOME/.local/bin/nfpm
ARCH=x86_64
DIST=$TOP/dist; WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
rm -rf "$DIST"; mkdir -p "$DIST"
NAME=bluplay-$VER

echo "== source tarball from $REF"
git archive --format=tar --prefix="$NAME/" "$REF" | gzip -9n > "$DIST/$NAME.tar.gz"
MD5=$(md5sum "$DIST/$NAME.tar.gz" | cut -d' ' -f1)

echo "== build binary"
tar xzf "$DIST/$NAME.tar.gz" -C "$WORK"
make -C "$WORK/$NAME" -j"$(nproc 2>/dev/null || echo 2)" CFLAGS="-O2" >/dev/null
BIN=$WORK/$NAME/bluplay; strip "$BIN"
"$BIN" --version >/dev/null 2>&1 || "$BIN" --help >/dev/null 2>&1 || true

echo "== prebuilt tarball"
P=$WORK/pre/$NAME-linux-$ARCH; mkdir -p "$P"
cp "$BIN" "$WORK/$NAME/README.md" "$WORK/$NAME/LICENSE" "$P/"
tar -C "$WORK/pre" --owner=0 --group=0 --numeric-owner -czf "$DIST/$NAME-linux-$ARCH.tar.gz" "$NAME-linux-$ARCH"

echo "== runtime deps"
GLIBC=$(objdump -T "$BIN" | grep -o 'GLIBC_[0-9.]*' | sed 's/GLIBC_//' | sort -uV | tail -1)
LIBS=$(objdump -p "$BIN" | awk '/NEEDED/{print $2}' | tr '\n' ' ')
echo "   NEEDED: $LIBS  (max symbol version GLIBC_$GLIBC)"
case " $LIBS " in *" libc.so.6 "*) ;; *) echo "unexpected libc" >&2; exit 1 ;; esac
for l in $LIBS; do case $l in libc.so.6|libm.so.6|ld-linux*) ;; *) echo "unexpected library $l: declare it" >&2; exit 1 ;; esac; done

echo "== deb/rpm (nfpm)"
sed -e "s/@VER@/$VER/g" -e "s/@GLIBC@/$GLIBC/g" -e "s#@BIN@#$BIN#g" -e "s#@SRC@#$WORK/$NAME#g" packaging/nfpm.yaml.in > "$WORK/nfpm.yaml"
"$NFPM" package -f "$WORK/nfpm.yaml" -p deb -t "$DIST/"
"$NFPM" package -f "$WORK/nfpm.yaml" -p rpm -t "$DIST/"

if [ $SLACK = 1 ]; then
  echo "== Slackware package (SlackBuild)"
  SB=$WORK/sb; mkdir -p "$SB"; cp slackbuild/bluplay/* "$SB/"; cp "$DIST/$NAME.tar.gz" "$SB/"
  RUN="sh"
  if [ ! -x /sbin/makepkg ] || [ "${MAKEPKG_LITE:-0}" = 1 ]; then
    mkdir -p "$WORK/shim"; cp scripts/makepkg-lite "$WORK/shim/makepkg"
    sed -i "s#/sbin/makepkg#$WORK/shim/makepkg#" "$SB/bluplay.SlackBuild"
  fi
  [ "$(id -u)" = 0 ] || RUN="unshare -r sh"
  PKGTYPE=txz VERSION=$VER TMP=$WORK/sbtmp OUTPUT=$DIST $RUN "$SB/bluplay.SlackBuild" >"$WORK/sb.log" 2>&1 || { tail -30 "$WORK/sb.log"; exit 1; }
fi

echo "== SHA256SUMS"
( cd "$DIST" && sha256sum -- * > SHA256SUMS && cat SHA256SUMS )
echo "slackbuild/bluplay/bluplay.info: VERSION=$VER MD5SUM=$MD5"
sed -i -e "s/^VERSION=.*/VERSION=\"$VER\"/" -e "s#^DOWNLOAD=.*#DOWNLOAD=\"https://github.com/fredrikspang-sys/bluplay/releases/download/v$VER/$NAME.tar.gz\"#" \
  -e "s/^MD5SUM=.*/MD5SUM=\"$MD5\"/" slackbuild/bluplay/bluplay.info
sed -i "s/^VERSION=\${VERSION:-.*}/VERSION=\${VERSION:-$VER}/" slackbuild/bluplay/bluplay.SlackBuild

if [ $UPLOAD = 1 ]; then
  GH=${GH:-gh}; command -v "$GH" >/dev/null || GH=$HOME/.local/bin/gh
  "$GH" release upload "v$VER" "$DIST"/* 
fi
