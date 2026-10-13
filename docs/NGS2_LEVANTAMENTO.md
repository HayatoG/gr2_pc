# Levantamento: NGS2 próprio para TLG e GR2

13/10/2026. Base para reimplementar do zero o `libSceNgs2` (mixer de software da Sony), para os ports não precisarem mais do `libSceNgs2.sprx` do firmware (TLG #11 / GR2 #8).

Fontes:
- **Rastreio dinâmico** do NGS2 nativo nos dois jogos (`TLG_NGS2_TRACE`, ver abaixo): GR2 ~4 min e TLG ~5 min, do título até o gameplay. São 4,5 milhões de `VoiceControl` no TLG e 110 mil no GR2.
- **Estudo estático:** TLG em [tlg_pc/analysis/03_audio.md](tlg_pc/analysis/03_audio.md) e GR2 em [gr2_pc/analysis/03_audio.md](gr2_pc/analysis/03_audio.md).
- **Referências gravadas** (ficam fora do git, porque são áudio do jogo): `~/decomp/ngs2_ref/`, com `*_trace*.txt` e `*_ref.wav` (a mixagem final do NGS2 nativo, float 8 canais, 48 kHz).

Legenda: **[C]** visto no rastreio ou no binário; **[D]** deduzido com boa confiança (layout batendo com o SDK público / shadPS4); **[H]** hipótese.

## 1. Conclusão

- **Um NGS2 serve aos dois jogos.** Os dois usam o mesmo middleware "sndx" da Sony por cima do NGS2. Chamam **as mesmas 10 funções** e quase o mesmo conjunto de parâmetros: 40 tipos no total, 36 em comum. [C]
- **A superfície é pequena e fechada:**

  | Funções | Uso |
  |---|---|
  | `SystemCreateWithAllocator` | criar o sistema |
  | `SystemRender` | render |
  | `RackQueryBufferSize`, `RackCreate`, `RackCreateWithAllocator`, `RackGetVoiceHandle` | racks e vozes |
  | `VoiceControl`, `VoiceGetState` (sempre `size` 0x30) | controle das vozes |
  | `SystemDestroy`, `RackDestroy` | destruição; nunca chamadas na sessão |

  Nenhuma chamada retornou erro. [C]
- **Saída:** um buffer float32 LE (tipo 0x18) de 8 canais e 256 frames por render, a 48 kHz. O GR2 pede um **segundo buffer mono** de 256 frames. [C]
- **Decodificadores:**
  - PCM;
  - **VAG/HEVAG** (tipo 0x1c);
  - **ATRAC9** (tipo 0x40), que no nativo passa pela nossa `runtime_ajm.c`. No nosso NGS2, o ATRAC9 pode chamar o LibAtrac9 direto. [C]
- **Ordem de dificuldade:** sampler + mixer + mastering primeiro. Depois os efeitos: filtro biquad, compressor, reverb I3DL2, EQ e o módulo custom (0x1c / 0x1d).
- Também temos a **saída do nativo gravada**, então cada etapa pode ser comparada número a número.

## 2. Grafo de racks [C]

| Rack ID | Tipo | Opção de criação (size) | Vozes | Observação |
|---|---|---|---|---|
| 0x1000 | SAMPLER | 0xa8 | 256 | uma voz por som tocando |
| 0x2000 | SUBMIXER | 0x98 | 1 por rack | ~40 racks: barramentos, categorias, FX "THRU/EQ/COMP/UMIX…" |
| 0x2001 | REVERB | 0x88 | 1 | I3DL2 |
| 0x3000 | MASTERING | 0x88 | 1 (TLG), 2 (GR2) | saída final |
| 0x4002 | CUSTOM SUBMIXER | 0x4d8 | 1 | módulos custom 0x1c/0x1d |

- **Opção do sistema** (0x40 bytes): `size` u64 em +0, nome, `maxGrainSamples`=512 em +0x1c, `numGrainSamples`=256 em +0x20, `sampleRate`=48000 em +0x24. [C, nomes D]
- **Opção de rack:** `size` u64 em +0 e nome[16]. Os mesmos campos aparecem nos offsets +0x1c (512), +0x20 (`maxVoices`), +0x24, +0x28 e +0x2c (8 = matrizes/canais). [C, nomes D]
- **Ligações vistas** (param PATCH): sampler → submixer; submixer → submixer / reverb / custom / mastering; reverb → submixer; custom → reverb / submixer. É um grafo de barramentos com até 5 portas de saída por voz de sampler (TLG). [C]
  - **[H]** O destino do PATCH dos samplers não bate com os handles de `GetVoiceHandle`. Nos exemplos, o destino é o **handle do rack** (a voz 0 parece ter o mesmo endereço que o rack). A implementação precisa aceitar os dois.

## 3. Parâmetros do `VoiceControl`

Cabeçalho: `u16 size; s16 next; u32 id`. `next` é o deslocamento em bytes até o próximo bloco (0 = fim). Nos jogos, o `next` vem sempre 0: um parâmetro por chamada. [C]

### Genéricos (qualquer rack)

| ID | Nome (SDK) [D] | Layout [C] | TLG | GR2 |
|---|---|---|---|---|
| 1 | MATRIX_LEVELS | `u32 matrix; u32 numLevels; float *levels` (8 ou 48 = 6×8 níveis) | ✔ | ✔ |
| 2 | PORT_VOLUME | `u32 port; float level` | ✔ | ✔ |
| 3 | PORT_MATRIX | `u32 port; u32 matrix` | ✔ | ✔ |
| 5 | PATCH | `u32 port; u32 destInput; void *destHandle` (NULL = desliga) | ✔ | ✔ |
| 6 | KICK_EVENT | `u32 event`: 0 PLAY, 1 RELEASE, 2 STOP, 3 KILL, 4 PAUSE, 5 RESUME | ✔ | ✔ |

### Sampler (0x1000)

| ID | Nome [D] | Layout [C] |
|---|---|---|
| 0x10000000 | SETUP | `u32 waveformType` (0x40 AT9, 0x1c VAG), `u32 channels` (1/2/4/6/8), `u32 sampleRate` (48000), `u32 configData` (AT9), `u32 frameOffset`, `u32 frameMargin`, `u32 flags` |
| 0x10000001 | ADD_WAVEFORM_BLOCKS | `void *data; u32 numBlocks; u32 flags; Block *blocks`; Block (32 B) = `u32 dataOffset, dataSize, numRepeats, numSkipSamples, numSamples, reserved; u64 userData` |
| 0x10000005 | PITCH | `float ratio` (≈0.9–1.0) |
| 0x10000006 | ENVELOPE | `u32 numPoints; u32 numReleasePoints; Point *points`; Point (12 B) = `u32 curve` (0/1/2), `u32 durationSamples`, `float height` |
| 0x10000009 | PEAK_METER (só GR2) | `u32 enable` |
| 0x1000000a | FILTER | `u32 index, location, type, channelMask…; float freq, resonance(0.5), gain(1.0)` |

### Submixer (0x2000)

| ID | Nome [D] | Observação |
|---|---|---|
| 0x20000000 | SETUP | `u32 numChannels` = 8 |
| 0x20000002 | COMPRESSOR | ~8 floats (threshold, ratio, attack, release, gain…) |
| 0x20000004 | USER_FX | **ponteiro para uma função do jogo** (sndx, ex. 0x800265540) e um contexto. O render precisa chamar código do jogo |
| 0x20000006 | FILTER | `index, location, type` (1/6/7/8…), `freq` (500/1000/24000), `resonance`, `gain`. Biquad por banda; é o parâmetro mais usado (1,2 M no TLG) |

### Reverb (0x2001)

| ID | Nome [D] | Layout [C] |
|---|---|---|
| 0x20010000 | SETUP | `u32 inChannels` = 8, `u32 outChannels` = 8 |
| 0x20010001 | I3DL2 (96 B) | `float wet, dry; s32 room, roomHF; u32 reflectionPattern; float decayTime, decayHFRatio; s32 reflections; float reflectionsDelay; s32 reverb; float reverbDelay, diffusion, density, hfReference`. O resto é reservado |

### Mastering (0x3000)

| ID | Nome [D] | Valores vistos |
|---|---|---|
| 0x30000000 | SETUP | 8 canais |
| 0x30000003 | LIMITER | enable=1, threshold=1.0 |
| 0x30000004 | GAIN | 1.0 / 1.0 (FBW, LFE) |
| 0x30000005 | OUTPUT (só GR2) | id 1. Provavelmente leva a 2ª voz de mastering ao buffer mono [H] |

### Custom (0x4002)

| ID | Observação |
|---|---|
| 0x40020000 | SETUP do rack custom |
| 0x40001c00 | módulo 0x1c (48 B, **só TLG**). Parâmetros de chorus/delay (taxa, profundidade, mix) [H] |
| 0x40001d00 | módulo 0x1d (136 B). Lista de pares (ganho, frequência): 70, 140, 210, 367… 920 Hz, com 7 ou 8 bandas. Parece **EQ paramétrico** [H] |

## 4. Plano de implementação

Arquivo novo `port/src/runtime_ngs2.c`, compartilhado pelos dois ports, ligado por `TLG_NGS2=hle`. O nativo continua sendo o padrão até a comparação ficar boa.

| Etapa | Conteúdo | Validação |
|---|---|---|
| 1 | Objetos sistema/rack/voz, alocador do jogo, `QueryBufferSize`, `GetVoiceHandle`, `VoiceGetState` (0x30), todos os parâmetros aceitos e guardados | o jogo roda igual ao placeholder mudo |
| 2 | Sampler PCM + VAG/HEVAG, blocos/loops, pitch (resample), envelope, eventos; submixer/mastering como soma com volume de porta e matriz | **SFX audível**; comparar com `*_ref.wav` |
| 3 | ATRAC9 via LibAtrac9 (até 8 canais, `configData`) | **BGM e diálogo** |
| 4 | Filtro biquad (sampler e submixer), compressor, limiter, gain | volume e timbre perto do nativo |
| 5 | Reverb I3DL2, módulos custom 0x1c/0x1d, USER_FX (chamar código do jogo) | ambiência |
| 6 | Trocar o padrão para `hle`, tirar o `libSceNgs2.sprx` da lista de arquivos necessários | Release sem arquivo de firmware |

Estimativa: etapas 1–3 em 2–3 semanas; 4–5 em mais 2–4.

## 5. Como repetir o rastreio

```
TLG_NGS2=native TLG_NGS2_TRACE=~/decomp/ngs2_ref/x_trace.txt TLG_NGS2_TRACE_WAV=~/decomp/ngs2_ref/x_ref.wav <rodar o jogo>
```

O código está em `port/src/runtime_ngs2_trace.c`, nas branches `feat/ngs2-hle` dos dois repositórios. Ele embrulha os imports do eboot que foram ligados ao `.sprx` e conta os parâmetros por (rack, id), guardando até 4 exemplos com os dados apontados. Também registra as ligações PATCH e grava a mixagem final.
