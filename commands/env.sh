# Source this from ~/.bashrc or ~/.zshrc to put every command on your PATH:
#   source ~/Documents/Vibes/commands/env.sh
# Adds each <name>/ subfolder of this directory to PATH, so a new command
# folder works as soon as you open a new shell. Location-independent:
# renaming or moving the parent folder won't break it (just update the
# source line in your rc file).
if [ -n "${BASH_VERSION:-}" ]; then
  _cmd_env_file="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
  _cmd_env_file="${(%):-%x}"
else
  _cmd_env_file="$0"
fi
_cmd_root="$(cd "$(dirname "$_cmd_env_file")" && pwd)"
for _cmd_dir in "$_cmd_root"/*/; do
  _cmd_dir="${_cmd_dir%/}"
  case ":$PATH:" in *":$_cmd_dir:"*) ;; *) PATH="$_cmd_dir:$PATH";; esac
done
export PATH
unset _cmd_env_file _cmd_root _cmd_dir
