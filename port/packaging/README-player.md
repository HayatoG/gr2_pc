# Gravity Rush 2 — port para PC / PC port

Por HayatoG · YouTube: [@hayatog-dev](https://www.youtube.com/@hayatog-dev) · Discord: [discord.gg/UMkdMYZh9g](https://discord.gg/UMkdMYZh9g) · Código: [github.com/HayatoG/gr2_pc](https://github.com/HayatoG/gr2_pc)

**Nenhum arquivo do jogo vem neste pacote.** Você precisa da sua própria cópia de Gravity Rush 2 para PS4. / **No game files are included.** You need your own copy of Gravity Rush 2 for PS4.

Versão experimental: o jogo vai do boot ao gameplay, mas ainda pode travar em áreas não testadas. / Experimental build: the game runs from boot to gameplay, but may still crash in untested areas.

---

## Português

### Arquivos do jogo necessários

Tudo vem do **seu** PS4 (GoldHEN + Itemzflow). Nada disso vai no download. Use **Gravity Rush 2 CUSA03694 (EUA) com o update 01.11**, montado numa pasta só, com o jogo base e o update por cima. São ~28 GB.

| Arquivo | Vem de | Tamanho | Para quê |
|---|---|---|---|
| `eboot.bin` | update 01.11 | 28 MB | o código do jogo (tem que ser o do 1.11) |
| `sce_module/libc.prx`, `libSceFios2.prx`, `libSceJobManager.prx` | jogo base | 1,7 MB | bibliotecas do próprio jogo |
| `sysdata/libSceSecure.prx` | jogo base | pequeno | criptografia do próprio jogo |
| `sce_sys/` (`param.sfo`, `playgo-chunk.dat`, `icon0.png`, `pic1.png`) | base + update | ~5 MB | metadados, instalação e a arte do launcher |
| `Gravite2_Chunk0.psarc`, `Gravite2_Chunk1.psarc` | jogo base | 10 + 15,8 GB | conteúdo principal |
| `Gravite2_Patch_Chunk0.psarc`, `Gravite2_Patch_Chunk1.psarc` | update 01.11 | 0,5 + 1,6 GB | correções do update |
| `sce_discmap.plt`, `sce_discmap_patch.plt` | update 01.11 | pequenos | mapa de arquivos |

**Do firmware do console (opcional: sem ele, o port usa o seu próprio mixer de áudio, ainda experimental):** `libSceNgs2.sprx`, de `/system/common/lib/` do seu PS4. Ele vai na pasta `system_lib/` ao lado do executável.

**Como montar a pasta:**
1. No Itemzflow, faça o dump do jogo (`CUSA03694`) e do update (`CUSA03694-patch`) para um pendrive exFAT.
2. No PC, copie a pasta do jogo base e depois copie o conteúdo do update **por cima**, substituindo os arquivos. Também dá para usar `scripts/make_game_view.py <base> <update> <saída>`, que monta a pasta com links, sem ocupar espaço.
3. Confira os tamanhos. Arquivos acima de 4 GB vindos pelo FTP do GoldHEN 2.2 chegam cortados, então use o pendrive.

**PC:** Windows 10 (1903+)/11 64 bits ou Linux x86-64 (glibc 2.39+), placa de vídeo com Vulkan 1.3 (6 GB de VRAM recomendados).

### Como jogar

1. Extraia o pacote numa pasta qualquer (no Windows, fora do .zip).
2. Coloque o `libSceNgs2.sprx` na pasta `system_lib/`, ao lado do executável (opcional: sem ele, o port usa o seu próprio mixer de áudio, ainda experimental).
3. Abra **Gravity Rush 2** (`Gravity Rush 2.exe` no Windows). No Windows, se aparecer "O Windows protegeu o computador", clique em *Mais informações* e depois em *Executar assim mesmo*. O programa não é assinado digitalmente.
4. Em **Pasta do jogo**, escolha a pasta que tem o `eboot.bin`. Escolha o idioma e clique em **Jogar**.

No Linux, `./install_desktop.sh` adiciona o jogo ao menu de aplicativos. No Windows, **Adicionar ao Steam** coloca o jogo na biblioteca do Steam (jogos não-Steam), com a arte do seu `pic1.png`; se o Steam estiver aberto, ele fecha por um momento e abre de novo.

### Durante o jogo
- **F10**: contador de FPS · **Insert** (ou R3 + L2): menu do port
- Controles de PS4/PS5, Xbox e 8BitDo via SDL3, por USB ou Bluetooth.

### Problemas
- **Linhas pretas perto dos personagens**: deixe ligada a opção "Desligar o contorno do geometry shader" no launcher (padrão).
- **Som incompleto ou estranho**: sem o `libSceNgs2.sprx` em `system_lib/`, o port usa o seu próprio mixer, ainda experimental. Com o arquivo, o áudio é o nativo.
- **Não abre ou fecha sozinho**: mande o `out/last_run.log` no [Discord](https://discord.gg/UMkdMYZh9g) ou numa [issue](https://github.com/HayatoG/gr2_pc/issues).

---

## English

### Required game files

Everything comes from **your own** PS4 (GoldHEN + Itemzflow). None of it is in the download. Use **Gravity Rush 2 CUSA03694 (US) with update 01.11**, merged into one folder, with the base game and the update on top. About 28 GB.

| File | From | Size | Purpose |
|---|---|---|---|
| `eboot.bin` | update 01.11 | 28 MB | the game code (must be the 1.11 one) |
| `sce_module/libc.prx`, `libSceFios2.prx`, `libSceJobManager.prx` | base game | 1.7 MB | the game's own libraries |
| `sysdata/libSceSecure.prx` | base game | small | the game's own cryptography |
| `sce_sys/` (`param.sfo`, `playgo-chunk.dat`, `icon0.png`, `pic1.png`) | base + update | ~5 MB | metadata, install info and the launcher art |
| `Gravite2_Chunk0.psarc`, `Gravite2_Chunk1.psarc` | base game | 10 + 15.8 GB | main content |
| `Gravite2_Patch_Chunk0.psarc`, `Gravite2_Patch_Chunk1.psarc` | update 01.11 | 0.5 + 1.6 GB | update fixes |
| `sce_discmap.plt`, `sce_discmap_patch.plt` | update 01.11 | small | file map |

**From the console firmware (optional: without it, the port uses its own audio mixer, still experimental):** `libSceNgs2.sprx`, from `/system/common/lib/` on your PS4. It goes in the `system_lib/` folder next to the executable.

**How to build the folder:**
1. In Itemzflow, dump the game (`CUSA03694`) and the update (`CUSA03694-patch`) to an exFAT USB drive.
2. On the PC, copy the base game folder, then copy the update's contents **over it**, replacing files. Or use `scripts/make_game_view.py <base> <update> <out>`, which builds the folder with links and uses no extra space.
3. Check the sizes. Files over 4 GB sent through GoldHEN 2.2's FTP arrive truncated, so use the USB drive.

**PC:** 64-bit Windows 10 (1903+)/11 or x86-64 Linux (glibc 2.39+), a graphics card with Vulkan 1.3 (6 GB of VRAM recommended).

### How to play

1. Extract the package anywhere (on Windows, outside the .zip).
2. Put `libSceNgs2.sprx` in the `system_lib/` folder next to the executable (optional: without it, the port uses its own audio mixer, still experimental).
3. Open **Gravity Rush 2** (`Gravity Rush 2.exe` on Windows). On Windows, if "Windows protected your PC" appears, click *More info*, then *Run anyway*. The program is not digitally signed.
4. Under **Game folder**, choose the folder that has `eboot.bin`. Pick the language and click **Play**.

On Linux, `./install_desktop.sh` adds the game to the applications menu. On Windows, **Add to Steam** puts the game in your Steam library (non-Steam games), with art from your `pic1.png`; if Steam is open, it closes for a moment and opens again.

### While playing
- **F10**: FPS counter · **Insert** (or R3 + L2): the port's menu
- PS4/PS5, Xbox and 8BitDo controllers via SDL3, over USB or Bluetooth.

### Problems
- **Black streaks near characters**: keep "Turn off the geometry-shader outline" checked in the launcher (default).
- **Incomplete or odd sound**: without `libSceNgs2.sprx` in `system_lib/`, the port uses its own mixer, still experimental. With the file, audio is native.
- **Does not start or closes by itself**: send `out/last_run.log` on [Discord](https://discord.gg/UMkdMYZh9g) or in an [issue](https://github.com/HayatoG/gr2_pc/issues).

---

This project is not affiliated with Sony Interactive Entertainment or SIE Japan Studio. Gravity Rush is a trademark of Sony Interactive Entertainment. / Este projeto não tem vínculo com a Sony Interactive Entertainment ou a SIE Japan Studio.
