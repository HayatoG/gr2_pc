# 03 — Áudio: Gravity Rush 2 (CUSA03694, eboot v1.00 / v1.11)

Levantamento estático para reimplementar o **libSceNgs2** do zero, em código comum aos ports do GR2 e do TLG. A estrutura segue `~/decomp/tlg_pc/analysis/03_audio.md`, que é a referência.
Endereços em espaço Ghidra (base 0x1000000) do **eboot 1.00** (`dump/eboot.bin`). O sndx do 1.11 (`dump/patch0/eboot.bin`, que é o eboot da game view) é o mesmo build, com a mesma string de build e a mesma data, só em outros endereços. Exemplo: a config do `sceSndxInit` fica em 0x24bc430 no 1.00 e em 0x25008c1 no 1.11.
Legenda: **[C]** = confirmado no binário/dados, **[D]** = deduzido com boa confiança (decompilação + headers públicos/shadPS4), **[H]** = hipótese/palpite.
Fontes: projeto Ghidra `analysis/ghidra/gr2_100.gpr` (ignorado pelo git), disassembly objdump do eboot 1.00, scan dos `.sxd` dentro dos psarc (só em memória), e os traces de runtime do NGS2 nativo em `~/decomp/ngs2_ref/{gr2,tlg}_trace.txt` (gerados pelo `port/src/runtime_ngs2_trace.c`). Quando um dado vem do trace, ele aparece como **[C, trace]**.

---

## 0. Resumo

- É o mesmo **SCE "sndx"** do TLG, linkado estático por cima de **libSceNgs2** + **libSceAudioOut**, mas **numa versão mais antiga**: branch `ps4sndx20160617_3500_gravity2_pause_eco_fix`, "Built at Oct 6 2016 15:18:39". O TLG usa `20160930_trico_lto`, de 27/out/2016. O sndx do GR2 não tem `sndxs_file_*`, captura (`sndx_capture_thread`), o FX `PANNER`, `maxSubmixers` nem o log de terminate. [C]
- Config: `"loadAudio3d=1 priority=%d maxInstances=1024 maxWaves=1024 maxSequences=1024 enableACP=1 enableRestricted=0 maxControllerSpeakers=1 cpuEnableFlags=0000111"`, com priority = 685 (0x2ad). As diferenças que importam para o NGS2 são **três** [C]:
  1. **Audio3d ligado.** As vozes 3D registram um **callback de voz do NGS2** (`0x10000008`), e o callback empurra o PCM da voz para `sceAudio3dObjectSetAttributes`.
  2. **`enableACP=1`.** O param de formato do sampler (`0x10000000`) leva flag=1 em +0x20, e o rack sampler pede `maxAjmAtrac9Decoders=256`: no firmware, o ATRAC9 é decodificado via libSceAjm/ACP. Num NGS2 próprio dá para ignorar e decodificar em software.
  3. **Controller speaker ligado** (`maxControllerSpeakers=1`). O mastering tem **2 vozes** e o `SystemRender` recebe **2 buffers**: MAIN float 8ch e PADSPK float **1ch**.
- Engine NGS2: 48 kHz, grain de 256, `maxGrainSamples` 512, saída float32 (NGS2 0x18). O grafo é sampler (256 vozes), depois 37 submixers de FX, 5 reverbs e 1 custom (DELAY), depois o premix e o mastering com limiter. [C, trace]
- Superfície NGS2 usada pelo eboot: **as mesmas 10 funções do TLG**. Imports de AudioOut (7) e Audio3d (12) também são idênticos aos do TLG. **Nenhum `sceAjm*` no eboot**: só o `libSceNgs2.sprx` importa Ajm. [C]
- Dados: **387 bancos SXD** (`sxd/*.sxd`, `*.sxd1`+`*.sxd2`) com **24.711 waves**: **0x42 ATRAC9 = 16.685** (voz, BGM e streams, de 1 a **8** canais), **0x21 HEVAG = 8.023** (SFX, de 1 a 6 canais, sample rates "tortos" como 44.066 a 47.999 Hz), **0x28 = 3** (dummy, 0 amostras). **Não tem PCM, MP3 nem 0x20.** Streams: 199 `.sxd1` (316 waves, todas ATRAC9, a maioria 6ch). [C]
- Buss FX do GR2 (`sxd/grvt2_buss.sxd`, 43 instâncias): **EQ 15, COMP 14, REVERB 5, UMIX 3, THRU 2, AMP 2, DISTO 1, DELAY 1**. Não usa CHORUS, PITCH nem PANNER. **UMIX, AMP e DISTO não são DSP do NGS2**: são callbacks do próprio sndx, que o NGS2 só precisa chamar (`0x20000004`). [C]

---

## 1. Inicialização, threads e render loop

### 1.1 Cadeia de init

```
FUN_01449xxx (SoundManager do jogo; trecho em 0x1449f12..0x144a10d)                [C]
 ├─ snprintf(buf, 0x100, cfg@0x24bc430, 0x2ad)
 ├─ FUN_0129f8a0(buf) = sceSndxInit (corpo FUN_0129f910; único caller)               [C]
 ├─ FUN_0129d3d0(&{callbacks 0x10a57d0, 0x10a5950, 0x10a5a20, …}) = sceSndxStreamSetHandlers [D]
 ├─ malloc(0x60000) → FUN_0129d8c0(0, buf, 0x60000, 6, 0) = sceSndxStreamBufferRegister   [D]
 │     (TLG: 0x200000 / 0x20. O GR2 usa só 384 KB de buffer de stream)
 ├─ FUN_0146c4d0("sxd/grvt2_buss.sxd", …)   carrega o bank de buss (BSFX)                [C]
 └─ FUN_01297910(…); FUN_01259670("Premix"); FUN_01259670("Default")  ≈ BussFxPatchByName [H]
```

### 1.2 Engine NGS2: `FUN_0125aee0` (sndx_engine_ngs2_orbis.c) [C]

O fluxo é o mesmo do `FUN_011a69c0` do TLG. Diferenças: não tem `maxSubmixers` (e por isso não existe o 4º rack), e o Audio3d **é ligado**.

1. `loadAudio3d=1`: roda `sceSysmoduleLoadModule(0xa7)` e liga `DAT_02856f80 = 1`. `noLoadNgs2=0`: roda `LoadModule(0xb)` e liga `DAT_02856f81 = 1`.
2. Chaves lidas (os defaults vêm entre parênteses, e o GR2 não passa nenhuma destas): `numGrains` (256, alinhado em 32 e limitado a 64..2048), `enableACP` (**1**), `numDecoderMemoryBlocks` (0, ≤16), `maxAtrac9Decoders` (256, ≤1024), `maxVoiceChannels` (256, ≤1024), `num/maxControllerSpeakers` (**1**, ≤4), `num/maxHeadsetSpeakers` (0), `enableRestricted` (**0**), `enableAUX` (0).
3. State global em `DAT_02856f88` (0x48f8 bytes), com o mutex `"sce_sndx_engine_update"` em +0x10 e os pools AT9 (+0x20) e channel (+0x38).
4. **Audio3d (vivo no GR2)**: `sceAudio3dInitialize(0)`, depois `GetDefaultOpenParameters`, depois `PortOpen(0xff, {0x20, granularity=numGrains, rate=0, maxObjects=0x200, queueDepth=3, bufferMode=2}, &DAT_028242c0)`. Em seguida `PortSetAttribute(port, 0x10001, &0.0f, 4)`, o event flag `"sndx_audio3d_notify"` e a thread `"sndx_audio3d_out_thread"` (entry `FUN_01264ea0`, corpo `FUN_0125c6d0`). Se o Audio3d falhar, o init inteiro aborta, e nada de som abre (detalhes em `port/src/runtime_gr2_audio3d.c`).
5. `sceNgs2SystemCreateWithAllocator(opt, &PTR_FUN_028242d0, &sys)`. A `opt` tem 0x40 bytes: `+0x1c maxGrainSamples=0x200`, `+0x20 numGrainSamples=0x100`, `+0x24 sampleRate=48000` [C, trace]. Obs.: o TLG passa exatamente o mesmo bloco. O "maxGrainSamples=0x100" do doc do TLG está errado: o valor certo é 0x200 em +0x1c e 0x100 em +0x20.
6. Racks via `sceNgs2RackCreateWithAllocator`. Os campos vêm do trace e da decompilação; os nomes seguem o layout do SDK/shadPS4 [D]:

| Rack ID | Tipo | Opção (tamanho) | Valores no GR2 |
|---|---|---|---|
| **0x3000** | MASTERING | 0x88 | grain 0x200, **maxVoices=2** (MAIN + 1 PADSPK; no TLG é 1), +0x24=1, +0x80 maxChannels=8, peak 8 |
| **0x2000** | SUBMIXER (premix) | 0x98 | grain 0x200, maxVoices 1, delay 1, matrices 1, ports 8; +0x80 ch=8, env=4, filters=8, inputs=1, peak=8 |
| **0x1000** | SAMPLER | 0xa8 | grain 0x200, maxVoices 0x100, matrices 1, ports 8; +0x80 maxChannelWorks 0x100; +0x84 **maxCodecCaches = 256 (ACP; seria 0x20 sem ACP)**; +0x88 waveformBlocks 0x10, envPoints 4; +0x90 filters 8, maxAtrac9Decoders 256; +0x98 atrac9ChannelWorks 0x100, **+0x9c maxAjmAtrac9Decoders = 256 (só com ACP)**; +0xa0 peak 8 |

   Configuração inicial via `RackGetVoiceHandle` + `VoiceControl`: mastering[0] recebe `0x30000000 {8ch}` e depois `6 {PLAY}`. O premix recebe `0x20000000 {8ch}`, `6 {PLAY}` e `5 PATCH → mastering`. Cada voz extra do mastering (PADSPK i) recebe `0x30000000 {8}`, depois `0x30000005 {portIndex=i}` e `6 {PLAY}` [C]. No TLG o laço de `0x30000005` existe, mas nunca roda. No GR2 roda 1 vez [C, trace].

### 1.3 Buss FX: `FUN_0125fe50` (= sceSndxBussFxSetup) e `FUN_01262840`/`FUN_01261430` (configure) [C]

Um rack por FX, criado com `RackQueryBufferSize` + `RackCreate` no heap do sndx. A string de init é `"numGrains=%d numBusses=%d bussIdMap=%s"`.

| Tipo de FX | Rack | Setup | Param de runtime |
|---|---|---|---|
| THRU, EQ, COMP | 0x2000 | `0x20000000 {8ch}` | EQ: `0x20000006` (48 B: banda, tipo, fc, Q, ganho) [D]; COMP: `0x20000002` (40 B) [D] |
| **DISTO, UMIX, AMP** | 0x2000 | `0x20000000 {8}` + **`0x20000004` (40 B) = callback de usuário** com função do sndx: DISTO→`FUN_01265500`, UMIX→`FUN_01265540`, AMP→`FUN_01265580` | O trace mostra os ponteiros `0x8_00265540`/`0x8_00265580` (base de carga 0x800000000) [C, trace] |
| REVERB | **0x2001** | `0x20010000 {8,8}` | `0x20010001` (96 B, estilo I3DL2: room, roomHF, decay, reflections, delay, diffusion, density, HFRef…). Os valores batem com `SysReverb`/`Reverb1..4` do bank [C, trace] |
| DELAY | **0x4002** (custom) | template de 0x4d8 bytes em `DAT_023e6b68`, módulo **0x1d**, módulo-opção `{0x14, 1, 8, 1000.0f}`; `0x40020000 {8,8}` | `0x40001d00` (136 B: inLevel, taps, tapDelay/Level, feedback, lowpass, dry/wet) [C, trace] |
| CHORUS / PITCH | 0x4002, módulos 0x1c / 0x20 | (código existe) | `0x40001c00` / `0x40002000`. **O GR2 não usa** [C] |

Mastering (premix "Premix", `outputLevel=1.000;isLimiterEnable=1`): `0x30000004 {1.0, 1.0}` = output level e `0x30000003 {1, 1.0}` = **limiter ligado** [C, trace]. O TLG manda os mesmos dois.

**Implicação**: o NGS2 próprio **não precisa** implementar upmix, distortion nem amp. Basta chamar o callback `0x20000004` de cada submixer no ponto certo da cadeia (assinatura a extrair de `FUN_01265540`/`FUN_01265500`) [D]. O doc do TLG trata UMIX/PANNER como "módulos built-in": é o mesmo mecanismo, e o TLG também tem 6 usos de `0x20000004` no trace.

Uso real no GR2 (bank `grvt2_buss.sxd`, chunks BSFX/GVAR/GVRN/BXFD/BXFN; 21 busses: System, Player, Enemy, Boss, Gimmik, NPC, Amb_Str, Amb_SFX, BGM, Demo, ComicDemo, Voice, System_Rev, Distance_Rev_Short/Long, Environment_Rev, Pad, Radio, Ingame, PreMaster, master) [C]:

| FX | Qtde GR2 | Qtde TLG | Exemplos GR2 |
|---|---|---|---|
| EQ (8 bandas: NONE/LS/PK/HS/LP/HP) | 15 | 11 | `PlayerEQ`, `BGMEQ`, `EQ17` (com **HP** e LP) |
| COMP | 14 | 6 | `Comp1..14` (isRms=0, threshold, ratio, attack/release, gain) |
| REVERB (0x2001) | 5 | 6 | `SysReverb`, `Reverb1..4` |
| UMIX | 3 | 5 | `AmbUpmix` (sur-input=REAR), `BGMUpmix`/`DemoUpmix` (**sur-input=SUR51**) |
| THRU | 2 | 8 | `Thru@System`, `Thru@Pad` |
| AMP | 2 | 0 | `Amp1`, `Amp2` (gain) |
| DISTO | 1 | 0 | `Dist1` (drive=8, gain=-20), no bus "Radio" [H] |
| DELAY (0x4002) | 1 | 3 | `Delay1` (3 taps de 250 ms, feedback 6,7, lowpass 8 kHz) |
| CHORUS / PANNER / PITCH | 0 | 2 / 1 / 0 | — |

Contagem de racks no trace do GR2 [C, trace]: 0x3000×1, 0x1000×1, **0x2000×38** (premix + 37 FX), **0x2001×5**, **0x4002×1**. Bate com o bank: 2+15+14+3+2+1 = 37 submixers. No TLG: 0x2000×32, 0x2001×6, 0x4002×5 (2 chorus + 3 delay).

GVAR (variáveis de ambiente que trocam presets): `eaves_small/large`, `tonnel_small/large`, `pit`, `another_zone`, `cave`… [C]

### 1.4 Threads e render [C]

| Thread | Entry / corpo | Função |
|---|---|---|
| `sndx_out_thread` | `FUN_012aba20` | render loop principal: `GetPortState` (main/bgm), depois `FUN_01263d10` (render), depois `sceAudioOutOutputs` (bloqueante = clock) |
| `sndx_audio3d_out_thread` | `FUN_01264ea0` → `FUN_0125c6d0` | `WaitEventFlag`, depois `sceAudio3dPortPush(port, 1)`. **Vivo no GR2** |
| `sndx_stream_schedule_thread`, `sndx_loader_thread` | (strings) | streaming de `.sxd2`, carregamento |

`FUN_01263d10` (render): formato da porta 4/5 → NGS2 0x12/0x13, 0x10/0x11 → 0x18/0x19. Depois `Lock(engine+0x10)`, `sceNgs2SystemRender(sys, bufInfo[], nPorts)`, `Unlock`, hooks pré e pós (+0x48c0/+0x48d0/+0x48b0/+0x48e8/`DAT_02856ff0`), e no fim `sceAudio3dPortGetQueueLevel`. Se houver espaço, `PortAdvance` + `SetEventFlag`. No trace: **2 buffers por render, `{0x2000 B, 0x18, 8ch}` e `{0x400 B, 0x18, 1ch}`**, 45.000 renders sem erro [C, trace].

### 1.5 Sampler / vozes [C]

- `FUN_0125cb90`: alocação de voz. Para voz 3D roda `sceAudio3dObjectReserve` (no GR2 é vivo); a liberação usa `ObjectUnreserve` (call em 0x125c620).
- `FUN_0125d980`: parâmetros de voz. Mapa SXD → waveform NGS2 (as constantes estão na decompilação; os nomes das NGS2 seguem o SDK [D]):
  - SXD 0x00→0x11, 0x01→0x10, 0x04→0x12, 0x05→0x13, 0x08→0x14, 0x09→0x15, 0x0c→0x16, 0x0d→0x17, 0x10→0x18, 0x11→0x19, 0x14→0x1a, 0x15→0x1b (as PCM I8/U8/I16/I24/I32/F32/F64, LE/BE)
  - **SXD 0x20/0x21 → 0x1c (VAG/HEVAG)**; 0x28 → 0x87; 0x30..0x35 → 0x81..0x86; **0x42 → 0x40 (ATRAC9)**, com configData do header; os outros caem em "Unsupported waveform type" → 0x80.
  - O bloco `0x10000000` (40 B) é `{type, channels, rate, configData, …, +0x20 = enableACP}`. No trace do GR2 o +0x20 vale **1**, no do TLG vale **0** [C, trace].
- `FUN_0125d170`: eventos. Mapa sndx → `6`(KICK): PLAY→0, PAUSE→4, RESUME→5, RELEASE→1, STOP→2. O sndx tem ainda o evento **VOICE_PEAK → `0x10000009 {1}`**, que no GR2 roda (1×) e no TLG não aparece no trace [C].
- `VoiceGetState(h, &st, 0x30)` é o único tamanho usado [C, trace].
- **Callback de voz** (Audio3d), em 0x125e384: se o Audio3d estiver carregado e a voz for 3D (`*(voice+0x130)+0xb3 == 1`), roda `VoiceControl(0x10000008, size 0x28, {+0x08 fn=FUN_0125f7c0, +0x10 userData=voz sndx, +0x18..0x27 = 0})` [C]. O `FUN_0125f7c0(info)` lê `info+0x08` (userData), `info+0x20` (flags; sai se `&0xc`), `*(info+0x00)` (ponteiro do PCM renderizado da voz) e `info+0x28` (nº de amostras). Depois chama `sceAudio3dObjectSetAttributes(port, obj, 5, …)` com POSITION(12 B), GAIN(4), SPREAD(4, ×2π), PRIORITY(4) e PCM(0x18 B, float mono) [C nos atributos, D no layout do `info`]. Obs.: no trace de 240 s não aparece nenhum `0x10000008`, então nesse trecho nenhuma voz 3D chegou a tocar [C, trace].

---

## 2. AudioOut: `sndx_audioout_orbis.c` [C]

- `FUN_012aa930`: start. Chaves: `numMainChannels`(8), `numGrainSamples`(256), `priority`/`stackSize`/`cpuEnableFlags` da thread `audioOut`, pad/headset/restricted/AUX e `enableBGM`(1). A tabela de portas fica em `DAT_02869380` (stride 0x20, fmt 0x10, 48000). Depois roda `sceAudioOutInit()`.
- `FUN_012ab860` = open por ID sndx (igual ao TLG): 0/0x78 → MAIN 8ch (0x78 com attr 0x10000), 0x79 → AUX, 0x7f → BGM, **100–103 → PADSPK 1ch + `sceAudioOutSetMixLevelPadSpk`**, 0x6e–0x71 → VOICE 2ch. Formatos 3/4/5 = FLOAT mono/stereo/8ch.
- No GR2 abrem **MAIN (8ch), BGM (só `GetPortState`) e 1 PADSPK (1ch, renderizado)**. `FUN_012ac320` tem o 2º call de `SetMixLevelPadSpk` (`sceSndxAudioOutSetMixLevelControllerSpeaker`).

## 3. Audio3d (vivo no GR2)

O caminho é o mesmo do TLG, com a diferença de que no GR2 ele está ligado. O stereo já está implementado no port em `port/src/runtime_gr2_audio3d.c`. **Interação com o NGS2**: o PCM de cada objeto vem do **callback de voz do sampler** (`0x10000008`), chamado durante o `SystemRender` com o buffer mono da voz. Então o NGS2 próprio precisa: (a) aceitar `0x10000008`; (b) renderizar a voz até o estágio pós-sampler (envelope/filtro/pitch) num buffer mono float por grain; (c) chamar `fn(info)` com esse buffer antes ou no lugar da mixagem dessa voz [D]. O roteamento real (se a voz 3D ainda vai para o bed) depende do sndx: ver `FUN_0125d980`/`FUN_0125f7c0` [H].

## 4. Controller speaker (vivo no GR2)

`maxControllerSpeakers=1` cria a 2ª voz do mastering, com porta 1, e a porta AudioOut PADSPK 1ch. O NGS2 precisa renderizar **N buffers de saída por `SystemRender`**, cada um com seus canais (8 e 1), e escolher qual voz do mastering vai para qual buffer via `0x30000005 {portIndex}` [C].

## 5. Formatos e dados de som [C]

Contagem sobre a view mesclada (patch por cima do base), com os psarc lidos em memória:

| Tipo | Arquivos | Tamanho | Conteúdo |
|---|---|---|---|
| `sxd/*.sxd` | 188 | 549 MB | banks completos: chunks TONE, REQD, NAME, WAVE, SEQD, LVAR/LVRN, RXFD/RXFN, DATA (+TRNS, TBLD) |
| `sxd/*.sxd1` | 199 | 22 MB | header de stream: REQD, NAME, WAVE (wave com flag 0x3 = dados externos) |
| `sxd/*.sxd2` | 199 | 737 MB | dados de stream (ATRAC9) |
| `sxd/grvt2_buss.sxd` | 1 | 25 KB | BSFX/GVAR/GVRN/BXFD/BXFN (buss FX) |
| `lua/sound/*.evd` | 87 | | eventos de som por cena |
| `mp4/**` | 283 | | vídeos (áudio via AvPlayer, **fora do NGS2**) |

Não tem `.bod`, `*_sbuf.data` nem `.scs` (isso é do TLG). O GR2 usa SXD puro, com o par `.sxd1`/`.sxd2` no lugar do SXDS.

Waves (24.711 no total; entrada da tabela WAVE: flags +0, codec +4, canais +5, rate +8, amostras +0x14, loop +0x18/+0x1c, tamanho +0x20):

| Codec SXD | → NGS2 | Waves | Canais | Rates | Onde |
|---|---|---|---|---|---|
| **0x42 ATRAC9** | 0x40 | 16.685 (16.369 em .sxd + 316 streams) | 1: 15.886, 2: 335, 4: 92, **6: 369**, **8: 3** | só 48 kHz | `voice_*` (12.082, mono), BGM/ambiência, todos os streams `.sxd1` (6ch: 287, 2ch: 24, 4ch: 2, 8ch: 3 = `ep90_01600m_*`, `ep90_01900m`) |
| **0x21 HEVAG** | 0x1c | 8.023 | 1: 7.116, 2: 879, 4: 23, 6: 5 | 48000 (5.953), 32000 (1.080), 44100 (657), mais ~200 valores tortos entre 31.993 e 47.999 | SFX (`*_se`, `town_se`, `player*_se`, cenas `ep*`) |
| 0x28 | 0x87 | 3 | 1 | 48 kHz, **0 amostras** | `town_se.sxd` (dummy) |
| 0x20 / PCM 0x00–0x15 / 0x30–0x35 | — | **0** | | | |

- Loops: 364 HEVAG e 254 ATRAC9 têm loop (2 deles são streams).
- Flags da wave: 0x1 (normal), 0x5 (2.085; [H] dados em outro ponto/DATA), 0x3 (stream externo `.sxd2`).
- **MP3: não existe.** Nenhum `.mp3`, nenhum codec MP3 no SXD, nenhum import de Ajm no eboot. O `runtime_ajm.c`/`runtime_mp3.c` não servem ao áudio do GR2. O ATRAC9 é decodificado **dentro** do NGS2: no firmware, com ACP, ele usa Ajm internamente, o que um NGS2 próprio pode substituir por LibAtrac9.
- O sampler tem que fazer **resample arbitrário** (HEVAG em 31.993..47.999 Hz para 48 kHz) e suportar ATRAC9 de **até 8 canais**.

---

## 6. Imports e exports (TLG × GR2)

Imports do eboot: TLG 1.03 (`tlg_pc/analysis/eboot_imports_1.03.json`), GR2 1.00 (`analysis/gr2/eboot_imports_1.00.json`) e GR2 1.11 (gerado agora, idêntico ao 1.00 nestas libs). "Usa" quer dizer chamado em runtime (estático + trace). "Import" quer dizer que está na tabela, mas o código não roda nesse jogo. [C]

| Função | TLG | GR2 |
|---|---|---|
| sceNgs2SystemCreateWithAllocator | usa | usa |
| sceNgs2SystemDestroy | import (shutdown) | import (shutdown) |
| sceNgs2SystemRender | usa (1 buffer) | usa (**2 buffers**) |
| sceNgs2RackCreateWithAllocator | usa (3) | usa (3) |
| sceNgs2RackQueryBufferSize / RackCreate | usa (42 FX) | usa (43 FX) |
| sceNgs2RackDestroy | import (shutdown) | import (shutdown) |
| sceNgs2RackGetVoiceHandle | usa | usa |
| sceNgs2VoiceControl | usa | usa |
| sceNgs2VoiceGetState (0x30) | usa | usa |
| demais 37 exports do sprx (abaixo) | — | — |
| sceAudioOutInit / Open / Output / Outputs / GetPortState / Close | usa | usa |
| sceAudioOutSetMixLevelPadSpk | import (pad desligado) | **usa** |
| sceAudio3dInitialize / GetDefaultOpenParameters / PortOpen / PortSetAttribute | import (morto) | **usa** |
| sceAudio3dObjectReserve / ObjectUnreserve / ObjectSetAttributes | import (morto) | **usa** |
| sceAudio3dPortGetQueueLevel / PortAdvance / PortPush | import (morto) | **usa** |
| sceAudio3dPortClose / Terminate | import | import (shutdown/falha) |
| sceAjm* | não | não |
| sceSysmoduleLoadModule(0xb NGS2 / 0xa7 Audio3d) | só 0xb | 0xb + **0xa7** |

**Exports do `libSceNgs2.sprx`** (o mesmo arquivo serve os dois ports: `gr2_pc/dump/system_lib` → `tlg_pc/dump/system_lib`), 47 ao todo: CalcWaveformBlock, CustomRackGetModuleInfo, FftInit/Process/QuerySize, GeomApply/CalcListener/ResetListenerParam/ResetSourceParam, GetWaveformFrameInfo, PanGetVolumeMatrix/PanInit, ParseWaveformData/File/User, RackCreate, RackCreateWithAllocator, RackDestroy, RackGetInfo, RackGet/SetUserData, RackGetVoiceHandle, RackLock/Unlock, RackQueryBufferSize, ReportRegister/UnregisterHandler, SystemCreate, SystemCreateWithAllocator, SystemDestroy, SystemEnumHandles, SystemEnumRackHandles, SystemGetInfo, SystemGet/SetUserData, SystemLock/Unlock, SystemQueryBufferSize, SystemRender, SystemSetGrainSamples, SystemSetSampleRate, VoiceControl, VoiceGetMatrixInfo, VoiceGetOwner, VoiceGetPortInfo, VoiceGetState, VoiceGetStateFlags. **Os dois jogos usam só 10 deles.**

**Imports do sprx** (iguais ao `tlg_pc/analysis/ngs2_imports.json`): libSceAjm (10: Initialize/Finalize, ModuleRegister/Unregister, InstanceCreate/Destroy, BatchJobControlBufferRa, BatchJobRunSplitBufferRa, BatchStartBuffer, BatchWait), libSceLibcInternal (32, matemática e strings, mais fopen/fread), libkernel (15: mutex, TSC, usleep, CompiledSdkVersion), e libSceFios2 (módulo necessário, nenhum símbolo).

---

## 7. Parâmetros do `sceNgs2VoiceControl`

Header `{u16 size; s16 next; u32 id}`. Os IDs estáticos do código sndx dos dois jogos são **praticamente iguais** (o GR2 não tem o `0x20000005` do TLG). A diferença está no que **roda**. As contagens de uso vêm dos traces de runtime, com GR2 a 240 s e TLG a 300 s [C, trace]. Os nomes são [D] quando não dito.

| Rack | ID | Tam. | Significado | GR2 | TLG |
|---|---|---|---|---|---|
| sampler | 1 | 24 | matrix levels (ponteiro p/ níveis) | 634 | 10.127 |
| todos | 2 | 16 | port volume {port, float} | sim | sim |
| sampler | 3 | 16 | port matrix {port, matrixId} | 5.072 | 81.016 |
| todos | 5 | 24 | PATCH {port, destHandle} | sim | sim |
| todos | 6 | 12 | KICK_EVENT 0 PLAY/1 RELEASE/2 STOP/4 PAUSE/5 RESUME [C] | sim | sim |
| sampler | 0x10000000 | 40 | waveform format {type, ch, rate, config, …, +0x20 ACP} [C] | 35 (**ACP=1**) | 4.547 (ACP=0) |
| sampler | 0x10000001 | 32 | waveform blocks (data ptr, nº de blocos, loop) | 383 | 9.562 |
| sampler | 0x10000003 | 16 | [H] seek/offset do stream ou update de bloco | estático | estático |
| sampler | 0x10000005 | 16 | pitch ratio (float) | 634 | 11.022 |
| sampler | 0x10000006 | 24 | [H] envelope/estado com ponteiro | 35 | 4.547 |
| sampler | 0x10000007 | 40 | [D] ADSR | estático | estático |
| sampler | **0x10000008** | 40 | **callback de voz** {fn, userData, flags} [C] | Audio3d (0 no trace) | nunca |
| sampler | **0x10000009** | 16 | peak meter {1} (sndx VOICE_PEAK) [D] | **1** | **0** |
| sampler | 0x1000000a | 48 | filtro biquad {índice, tipo, fc, Q, ganho} | 1.455 | 18.307 |
| submixer | 0x20000000 | 16 | setup {nCh=8} | 38 | 32 |
| submixer | 0x20000002 | 40 | compressor | 7.994 | 25.149 |
| submixer | **0x20000004** | 40 | **callback de FX do usuário** (UMIX/AMP/DISTO; PANNER no TLG) [C] | 6 | 6 |
| submixer | 0x20000006 | 48 | banda de EQ | 56.589 | 254.421 |
| reverb | 0x20010000 / 0x20010001 | 24 / 96 | setup {8,8} / I3DL2 | 5 / 2.969 | 6 / 17.754 |
| mastering | 0x30000000 | 16 | setup {8ch} | 2 | 1 |
| mastering | 0x30000003 / 0x30000004 | 16 | limiter on / output level | 1 / 1 | 1 / 1 |
| mastering | **0x30000005** | 16 | índice da porta de saída | **1** | 0 |
| custom | 0x40020000 | 24 | setup {8,8} | 1 | 5 |
| custom | 0x40001c00 | 48 | chorus (módulo 0x1c) | **0** | 3.236 |
| custom | 0x40001d00 | 136 | delay (módulo 0x1d) | 1.825 | 48.483 |
| custom | 0x40002000 | ? | pitch shifter (módulo 0x20) | 0 | 0 |

**Só no GR2 (em runtime)**: `0x10000000` com ACP=1, `0x10000008` (callback de voz/Audio3d, quando há voz 3D), `0x10000009` (peak), `0x30000005` (porta PADSPK), mastering com 2 vozes e render com 2 buffers. **Só no TLG**: `0x40001c00` (chorus). O PANNER existe só no sndx do TLG, também via `0x20000004`.

---

## 8. Implicações para o NGS2 próprio

**Comum aos dois jogos (núcleo obrigatório):**
- API: as 10 funções (`SystemCreateWithAllocator`, `SystemRender`, `SystemDestroy`, `RackQueryBufferSize`, `RackCreate`, `RackCreateWithAllocator`, `RackDestroy`, `RackGetVoiceHandle`, `VoiceControl`, `VoiceGetState`(0x30)). Alocador do jogo, buffer fornecido no `RackCreate` e cadeia de params `{size, next, id}`.
- 48 kHz, grain de 256, saída float32 LE (0x18), 8 canais no MAIN.
- Grafo: sampler (até 256 vozes), PATCH para submixers/FX, premix, mastering (setup 8ch, output level, **limiter**).
- Sampler: formato (`0x10000000`), blocos/loop (`0x10000001`), pitch com **resample arbitrário** (`0x10000005`), envelope (`0x10000006/7`), biquad (`0x1000000a`), matrix/port volume/matrix (1/2/3), KICK (PLAY/RELEASE/STOP/PAUSE/RESUME), estado de voz.
- Decoders: **HEVAG/VAG (0x1c)** de 1 a 6 canais e **ATRAC9 (0x40)** de 1 a 8 canais (LibAtrac9). PCM é trivial e os dois jogos quase não usam.
- FX nativos do NGS2: **EQ** (`0x20000006`, 8 bandas, inclusive HP/LP), **compressor** (`0x20000002`), **reverb I3DL2** (rack 0x2001), **delay multi-tap** (custom 0x4002/0x1d).
- **Callback de FX do submixer (`0x20000004`)**: só chamar a função do jogo. UMIX/AMP/DISTO (e o PANNER do TLG) são DSP do sndx, rodando dentro do render do NGS2.

**Só no GR2:**
- **Callback de voz `0x10000008`**, chamado por grain com o PCM mono pós-sampler da voz (alimenta o Audio3d). Sem ele, as vozes 3D ficam mudas.
- **Vários buffers de saída por render** (8ch + 1ch) e mastering multi-voz com `0x30000005` (porta por índice) para o controller speaker.
- `0x10000009` (peak meter da voz), quando o jogo pede.
- ACP ligado: aceitar e ignorar a flag +0x20 do `0x10000000` e os campos `maxCodecCaches`/`maxAjmAtrac9Decoders` do rack sampler.
- ATRAC9 **8ch** e streams 5.1 (6ch) com UMIX `sur-input=SUR51`.

**Só no TLG:** chorus (custom 0x1c), PANNER (callback) e o `0x20000005` estático.

**Fora do NGS2 (nos dois):** Audio3d (já em `runtime_gr2_audio3d.c`), AudioOut (`runtime_audio.c`), vídeos mp4 (AvPlayer). MP3/Ajm não entram no áudio de nenhum dos dois.

---

## 9. Tabela de endereços (eboot 1.00)

| Endereço | O quê | Status |
|---|---|---|
| 0x24bc430 | string de config do sceSndxInit (no 1.11: 0x25008c1) | C |
| 0x24bc4ca | `"sxd/grvt2_buss.sxd"` | C |
| 0x1449f12 | SoundManager: snprintf(config, 685) + sceSndxInit | C |
| 0x129f8a0 / 0x129f910 | sceSndxInit / corpo | C |
| 0x129d3d0 / 0x129d8c0 | sceSndxStreamSetHandlers / StreamBufferRegister | D |
| 0x125aee0 | init do engine NGS2 (Audio3d, System, 3 racks) | C |
| 0x125cb90 | alocação de voz (Audio3d ObjectReserve) | C |
| 0x125d170 | eventos de voz (PLAY/PAUSE/RESUME/RELEASE/STOP/PEAK) | C |
| 0x125d980 | parâmetros de voz (SXD→NGS2, 0x10000000…0x1000000a, registro do callback) | C |
| 0x125e384 | registro do callback `0x10000008` | C |
| 0x125f7c0 | callback de voz → sceAudio3dObjectSetAttributes | C |
| 0x125fe50 | sceSndxBussFxSetup (racks de FX) | C |
| 0x1261430 / 0x1262840 | configure de buss FX (mastering/limiter, EQ/comp/delay) | C |
| 0x1265500 / 0x1265540 / 0x1265580 | callbacks de FX do sndx: DISTO / UMIX / AMP | C |
| 0x1263d10 | render (SystemRender + Audio3d advance) | C |
| 0x1264ea0 → 0x125c6d0 | sndx_audio3d_out_thread (PortPush) | C |
| 0x12aa930 | start do AudioOut | C |
| 0x12ab860 | open de porta por ID sndx (+SetMixLevelPadSpk) | C |
| 0x12aba20 | sndx_out_thread (render → AudioOutOutputs) | C |
| DAT_02856f88 | state global do engine | C |
| DAT_02856f80 / 81 | flags "Audio3d carregado" / "NGS2 carregado" | C |
| DAT_028242c0 | porta Audio3d | C |
| PTR_FUN_028242d0 | alocador NGS2 do sndx | C |
| DAT_023e6b68 | template do custom rack 0x4002 (0x4d8 B) | C |
| DAT_02869380 | tabela de portas AudioOut do sndx | C |
