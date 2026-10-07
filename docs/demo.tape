# Records docs/demo.gif against a throwaway copy of examples/demo-vault:  vhs docs/demo.tape
Output docs/demo.gif
Set Shell "bash"
Set FontSize 17
Set Width 1180
Set Height 680
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Hide
Type "export PATH=$PWD/.venv/bin:$PATH D=$(mktemp -d); export XDG_CONFIG_HOME=$D/c XDG_STATE_HOME=$D/s XDG_CACHE_HOME=$D/k PS1='\[\e[35m\]vault\[\e[0m\] $ '; cp -R examples/demo-vault $D/vault && bl init $D/vault >/dev/null && bl config heading '## Log' >/dev/null && cd $D/vault && clear"
Enter
Sleep 1s
Show

Type 'bl "coffee with Maya about the Lumen raise, Northwind may lead"'
Enter
Sleep 2.5s
Type 'bl -t "send Priya the market making memo fri"'
Enter
Sleep 2.5s
Type 'bl "lunch with Sam"'
Enter
Sleep 2.5s
Type 'bl --to Jonas "wants a weekly update"'
Enter
Sleep 2.5s
Type "clear && cat Daily/$(date +%F).md"
Enter
Sleep 4s
Type "bl undo"
Enter
Sleep 2.5s
