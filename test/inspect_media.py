from pathlib import Path
import re
s=Path('test/tools/vidu-media.js').read_text(encoding='utf8')
for match in re.finditer(r'setRemote|audioTrack|remoteAudio|AudioPlayer|setAudio|srcObject|playAudio|subscribeStream',s):
 print(s[max(0,match.start()-130):match.end()+250])
