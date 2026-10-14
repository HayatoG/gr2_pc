/* libSceNgs2 reimplemented from scratch: the software mixer Sony's "sndx" middleware drives.
 *
 * Written against the API surface traced from the console module in The Last Guardian and
 * Gravity Rush 2 (docs/NGS2_LEVANTAMENTO.md): ten functions, five rack types, and the
 * VoiceControl parameter blocks those games send. Nothing here is specific to one game; the
 * selection between this mixer and the firmware module is TLG_NGS2 (native = the console's
 * libSceNgs2.sprx linked as a module; anything else = this file).
 *
 * Model:
 *   - A system owns racks; a rack owns voices. Handles are host objects tagged with a magic.
 *     Voice 0 of a rack is the rack handle itself (the console module does the same: sndx
 *     patches sampler ports to rack handles), any other voice has its own object.
 *   - Sampler voices decode PCM, VAG/HEVAG or ATRAC9 (LibAtrac9) from queued waveform blocks,
 *     resample to the system rate (cubic, pitch ratio * source rate), apply the envelope and mix
 *     through each patched port (volume and an output-major matrix: level[out * in_ch + in]).
 *   - Submixer, reverb, custom and mastering voices are buses: inputs are summed, effects run,
 *     and the result goes on through their own ports. Buses are processed in dependency order
 *     each render. Mastering voices write the render buffers (output id = buffer index).
 *   - Filters, compressor, distortion, reverb, chorus and delay are parsed and stored but not
 *     processed yet: reverb racks pass only their dry part (sends are wet), custom racks pass
 *     their input through. User FX handlers (guest functions) are called.
 *   - VoiceGetState: sndx frees a voice when INUSE (bit 0) drops, so INUSE stays set from setup
 *     until the voice ends (blocks exhausted, release finished, STOP/KILL).
 *
 * Environment (TLG_ prefix; ports with another prefix alias it):
 *   TLG_NGS2=native|hle      firmware module or this mixer (default: this mixer)
 *   TLG_NGS2_LOG=1           unknown parameters, decoder errors, a summary every 30 s
 *   TLG_NGS2_WAV=<file>      writes render buffer 0 as float WAV (compare with the native mix)
 *   TLG_NGS2_USERFX=0        do not call the game's user FX handlers
 *   TLG_NGS2_REVERB=pass     reverb racks pass their input through instead of the dry part
 *   TLG_NGS2_CUSTOM=mute     custom racks (chorus/delay) output silence instead of their input
 *
 * HEVAG coefficients: vgmstream (ISC license), src/coding/psv_decoder.c. */
#define _GNU_SOURCE
#include "runtime.h"
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "third_party/LibAtrac9/C/src/libatrac9.h"

#define NGS2_OK 0
#define NGS2_ERR_HANDLE ((int32_t)0x804A0230)
#define NGS2_ERR_ARG ((int32_t)0x804A0201)
#define NGS2_ERR_MEMORY ((int32_t)0x804A0050)

#define MAGIC_SYSTEM UINT32_C(0x4e325359)
#define MAGIC_RACK UINT32_C(0x4e325241)
#define MAGIC_VOICE UINT32_C(0x4e32564f)

#define MAX_CH 8
#define MAX_GRAIN 1024
#define MAX_PORTS 16
#define MAX_MATRICES 16
#define MAX_LEVELS (MAX_CH * MAX_CH)
#define MAX_BLOCKS 64
#define MAX_ENV 16
#define MAX_FILTERS 8
#define FIFO_FRAMES 2048
#define UNIT_FRAMES 256
#define END_GRACE_RENDERS 2

enum { RACK_SAMPLER = 0x1000, RACK_SUBMIXER = 0x2000, RACK_REVERB = 0x2001, RACK_MASTERING = 0x3000 };
enum { KIND_SAMPLER, KIND_SUBMIXER, KIND_REVERB, KIND_MASTERING, KIND_CUSTOM };
enum { EV_PLAY, EV_RELEASE, EV_STOP, EV_KILL, EV_PAUSE, EV_RESUME };
enum { ST_FREE, ST_READY, ST_PLAYING };
#define FLAG_INUSE 0x1u
#define FLAG_PLAYING 0x2u
#define FLAG_PAUSED 0x4u
#define FLAG_EMPTY 0x20u

enum {
    WAVE_PCM_U8 = 0x10, WAVE_PCM_I8 = 0x11, WAVE_PCM_I16L = 0x12, WAVE_PCM_I16B = 0x13,
    WAVE_PCM_I24L = 0x14, WAVE_PCM_I24B = 0x15, WAVE_PCM_I32L = 0x16, WAVE_PCM_I32B = 0x17,
    WAVE_PCM_F32L = 0x18, WAVE_PCM_F32B = 0x19, WAVE_PCM_F64L = 0x1a, WAVE_PCM_F64B = 0x1b,
    WAVE_VAG = 0x1c, WAVE_ATRAC9 = 0x40,
};

/* ---- Guest-visible layouts ---- */
typedef struct { uint16_t size; int16_t next; uint32_t id; } ParamHeader;
typedef struct { void *host_buffer; uint64_t host_size; uintptr_t reserved[5]; uintptr_t user_data; } BufferInfo;
typedef ABI int32_t (*AllocHandler)(BufferInfo *);
typedef struct { AllocHandler alloc, free; uintptr_t user_data; } Allocator;
typedef struct { void *buffer; uint64_t size; uint32_t waveform, channels; } RenderBuffer;
typedef struct { uint32_t data_offset, data_size, repeats, skip, samples, reserved; uint64_t user_data; } GuestBlock;
typedef struct { uint32_t curve, duration; float height; } EnvPoint;
typedef struct {
    float **channels;
    uintptr_t user0, user1, user2;
    uint32_t flags, num_channels, num_grain_samples, sample_rate;
} UserFxContext;
typedef ABI int32_t (*UserFxHandler)(UserFxContext *);
typedef struct {
    uintptr_t callback_data, voice;
    uint32_t flag, reserved;
    uintptr_t user_data;
    const void *data;
    uint32_t data_size, repeated, attributes, reserved2;
} CallbackInfo;
typedef ABI void (*CallbackHandler)(const CallbackInfo *);
_Static_assert(sizeof(BufferInfo) == 64, "NGS2 buffer info");
_Static_assert(sizeof(GuestBlock) == 32, "NGS2 waveform block");
_Static_assert(sizeof(EnvPoint) == 12, "NGS2 envelope point");
_Static_assert(sizeof(UserFxContext) == 48, "NGS2 user FX context");
_Static_assert(sizeof(CallbackInfo) == 56, "NGS2 callback info");

/* ---- Host objects ---- */
typedef struct System System;
typedef struct Rack Rack;
typedef struct Voice Voice;

typedef struct { Voice *dest; uint32_t input, delay; float volume; int32_t matrix; } Port;
typedef struct { const uint8_t *data; uint32_t size, repeats, skip, samples; uint64_t user; } Block;
typedef struct { uint32_t count; float level[MAX_LEVELS]; } Matrix;
typedef struct { uint32_t index, location, type, mask; float a, b, c, d, e; } Filter;

typedef struct {
    /* Waveform */
    uint32_t wave, wave_channels, rate, config;
    float pitch;
    Block blocks[MAX_BLOCKS];
    uint32_t head, count;
    /* Current block */
    int started;
    uint32_t byte, out_left, skip_left, repeated;
    /* Decoders */
    float hist[MAX_CH][4];
    void *at9;
    Atrac9CodecInfo at9_info;
    uint32_t at9_frame_in_superframe, at9_superframe_start;
    int at9_ok;
    /* Decoded frames waiting for the resampler (interleaved, MAX_CH stride) */
    float *fifo;
    uint32_t fifo_len;
    double pos;
    int source_done, empty_renders;
    /* Envelope */
    EnvPoint env[MAX_ENV];
    uint32_t env_forward, env_release, env_segment, env_position;
    float env_start, env_level;
    int releasing;
    /* State reported to the game */
    uint64_t decoded_samples, decoded_bytes, user;
    const void *waveform_pointer;
} Sampler;

struct Voice {
    uint32_t magic;
    Rack *rack;
    uint32_t index;
    uint32_t state;
    int paused;
    uint32_t channels;
    Port ports[MAX_PORTS];
    Matrix *matrices;
    float peak;
    Filter filters[MAX_FILTERS];
    uint32_t num_filters;
    UserFxHandler user_fx;
    uintptr_t user_fx_data[3];
    CallbackHandler callback;
    uintptr_t callback_data;
    uint32_t callback_flags;
    Sampler *sampler;
    /* Buses */
    float *input;           /* MAX_CH planar channels of MAX_GRAIN */
    int has_input;
    float compressor[8];
    float reverb[24];
    float dry, wet;
    uint32_t output_id, limiter, out_channels;
    float limiter_threshold, gain_fbw, gain_lfe;
    uint8_t custom[256];
    int stopped;            /* bus: RELEASE/STOP/KILL received (buses never kicked still run) */
    /* Render order */
    int pending, visited;
};

struct Rack {
    uint32_t magic;          /* first: the rack handle is also voice 0's handle */
    System *system;
    uint32_t id, kind, max_voices, max_ports, max_matrices;
    Voice **voices;
    BufferInfo buffer;
    Allocator allocator;
    int allocated;
    Rack *next;
};

struct System {
    uint32_t magic;
    uint32_t grain, max_grain, rate;
    Rack *racks;
    BufferInfo buffer;
    Allocator allocator;
    int allocated;
    uint64_t renders;
    System *next;
};

static pthread_mutex_t lock = PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP;
static System *systems;
static FILE *wav;
static uint64_t wav_frames;
static uint32_t wav_channels;
static uint64_t stat_plays, stat_finished, stat_blocks, stat_errors, stat_user_fx, stat_starved;

static const float hevag_coefs[128][4] = {
    {0.0f, 0.0f, 0.0f, 0.0f},
    {0.9375f, 0.0f, 0.0f, 0.0f},
    {1.796875f, -0.8125f, 0.0f, 0.0f},
    {1.53125f, -0.859375f, 0.0f, 0.0f},
    {1.90625f, -0.9375f, 0.0f, 0.0f},
    {1.7982178f, -0.86169434f, 0.0f, 0.0f},
    {1.770874f, -0.89916992f, 0.0f, 0.0f},
    {1.6992188f, -0.91821289f, 0.0f, 0.0f},
    {1.6031494f, -0.9375f, 0.0f, 0.0f},
    {1.4682617f, -0.9375f, 0.0f, 0.0f},
    {1.3139648f, -0.9375f, 0.0f, 0.0f},
    {1.1424561f, -0.9375f, 0.0f, 0.0f},
    {0.95605469f, -0.9375f, 0.0f, 0.0f},
    {0.75695801f, -0.9375f, 0.0f, 0.0f},
    {0.54785156f, -0.9375f, 0.0f, 0.0f},
    {0.33166504f, -0.9375f, 0.0f, 0.0f},
    {0.11108398f, -0.9375f, 0.0f, 0.0f},
    {-0.11108398f, -0.9375f, 0.0f, 0.0f},
    {-0.33166504f, -0.9375f, 0.0f, 0.0f},
    {-0.54785156f, -0.9375f, 0.0f, 0.0f},
    {-0.75695801f, -0.9375f, 0.0f, 0.0f},
    {-0.95605469f, -0.9375f, 0.0f, 0.0f},
    {-1.1424561f, -0.9375f, 0.0f, 0.0f},
    {-1.3139648f, -0.9375f, 0.0f, 0.0f},
    {-1.4682617f, -0.9375f, 0.0f, 0.0f},
    {-1.6031494f, -0.9375f, 0.0f, 0.0f},
    {-1.6992188f, -0.91821289f, 0.0f, 0.0f},
    {-1.770874f, -0.89916992f, 0.0f, 0.0f},
    {-1.7982178f, -0.86169434f, 0.0f, 0.0f},
    {0.65625f, -1.125f, 0.40625f, -0.375f},
    {-0.78125f, -0.875f, -0.40625f, -0.28125f},
    {-1.28125f, -0.90625f, -0.4375f, -0.125f},
    {-0.020385742f, -0.33227539f, -0.060302734f, -0.066040039f},
    {-0.90698242f, -0.27111816f, -0.28051758f, 0.051757812f},
    {-0.97668457f, -0.38647461f, -0.34350586f, 0.03527832f},
    {0.73461914f, -0.57983398f, 0.32336426f, -0.15844727f},
    {0.46362305f, -0.84790039f, 0.47302246f, -0.1484375f},
    {-1.0054932f, -0.31689453f, -0.25280762f, 0.027709961f},
    {1.1229248f, 0.24194336f, -0.16870117f, -0.28271484f},
    {1.5894775f, -0.37158203f, -0.46289062f, 0.15466309f},
    {1.6005859f, -0.54772949f, -0.2746582f, 0.20324707f},
    {-0.20361328f, -0.45703125f, -0.78808594f, 0.10253906f},
    {0.95446777f, -0.52832031f, 0.25769043f, -0.061767578f},
    {1.168335f, -0.16308594f, -0.092407227f, 0.059448242f},
    {1.2246094f, -0.31274414f, 0.036621094f, 0.024291992f},
    {-0.57922363f, -0.50317383f, -0.66967773f, -0.18225098f},
    {-0.71972656f, 0.2902832f, -0.58435059f, -0.84802246f},
    {-0.14562988f, -1.112915f, -0.15100098f, -0.38012695f},
    {0.33972168f, -0.86767578f, -0.19226074f, -0.17663574f},
    {-0.89526367f, -0.25170898f, -0.27001953f, 0.054443359f},
    {0.7479248f, -0.3145752f, -0.038452148f, -0.0021972656f},
    {1.1544189f, -0.22680664f, 0.012451172f, 0.031494141f},
    {0.96142578f, -0.54724121f, 0.25952148f, -0.065673828f},
    {-0.87548828f, -0.21911621f, -0.25256348f, 0.058837891f},
    {-0.89819336f, -0.2565918f, -0.27258301f, 0.053710938f},
    {-1.1193848f, -0.42834473f, -0.32641602f, -0.047729492f},
    {-0.32202148f, -0.32312012f, -0.23547363f, -0.1998291f},
    {0.2286377f, 1.1209717f, 0.22705078f, -0.70141602f},
    {1.1247559f, 0.22692871f, -0.13720703f, -0.29626465f},
    {1.6118164f, -0.36767578f, -0.50524902f, 0.16723633f},
    {1.5181885f, -0.58496094f, -0.03125f, 0.075927734f},
    {-0.32385254f, -0.13964844f, -0.38842773f, -0.83959961f},
    {1.1390381f, -0.12792969f, -0.10107422f, 0.061889648f},
    {0.20043945f, -0.075683594f, -0.11547852f, -0.51623535f},
    {0.51831055f, -0.92590332f, -0.065063477f, -0.27575684f},
    {-1.097168f, -0.47497559f, -0.34265137f, 0.0053710938f},
    {-0.31274414f, -0.3338623f, -0.21118164f, -0.23181152f},
    {0.38842773f, -0.058959961f, -0.087158203f, -0.17346191f},
    {0.96887207f, -0.46923828f, 0.34436035f, -0.12438965f},
    {1.229126f, -0.31848145f, 0.038330078f, 0.023803711f},
    {1.0253906f, -0.40246582f, 0.18933105f, -0.018920898f},
    {-1.0411377f, -0.33874512f, -0.296875f, -0.041015625f},
    {1.1568604f, -0.22973633f, 0.013183594f, 0.03125f},
    {0.0091552734f, -0.27355957f, -0.036376953f, -0.84680176f},
    {-1.1160889f, -0.5078125f, -0.36169434f, 0.00061035156f},
    {-0.88745117f, -0.23901367f, -0.26318359f, 0.056152344f},
    {-0.33447266f, 0.45715332f, 0.72460938f, -0.13293457f},
    {1.0977783f, 0.23779297f, -0.083374023f, -0.33007812f},
    {1.5992432f, -0.34606934f, -0.47045898f, 0.12878418f},
    {1.164917f, -0.23937988f, 0.015869141f, 0.030517578f},
    {0.64355469f, -0.52124023f, 0.38134766f, -0.38537598f},
    {-0.93945312f, -0.41296387f, -0.3548584f, -0.055664062f},
    {0.89221191f, 0.3079834f, 0.052978516f, -0.30041504f},
    {1.2542725f, -0.34997559f, 0.047729492f, 0.020996094f},
    {1.3354492f, -0.45422363f, 0.081176758f, 0.01184082f},
    {0.0029296875f, -0.037841797f, -0.15405273f, 0.0390625f},
    {-0.99145508f, -0.29431152f, -0.28210449f, -0.033081055f},
    {-1.0389404f, -0.37438965f, -0.28527832f, 0.019897461f},
    {0.039794922f, -0.46948242f, 0.051147461f, -0.1138916f},
    {1.0858154f, 0.26782227f, -0.066040039f, -0.3515625f},
    {1.4737549f, -0.22900391f, -0.24621582f, -0.073364258f},
    {1.0655518f, -0.41784668f, 0.2043457f, -0.020629883f},
    {1.5808105f, -0.46960449f, -0.36706543f, 0.23754883f},
    {1.2253418f, -0.3137207f, 0.036865234f, 0.024169922f},
    {1.1456299f, -0.33654785f, 0.12304688f, 0.0050048828f},
    {-0.57617188f, -0.61108398f, -0.34814453f, -0.14172363f},
    {0.96057129f, -0.52807617f, 0.26062012f, -0.061157227f},
    {0.29907227f, -1.0494385f, 0.15856934f, -0.33935547f},
    {1.2441406f, -0.33728027f, 0.043945312f, 0.022094727f},
    {1.3809814f, -0.51428223f, 0.10168457f, 0.0064697266f},
    {1.239502f, -0.33154297f, 0.042114258f, 0.022583008f},
    {1.1765137f, -0.17297363f, -0.08996582f, 0.058837891f},
    {0.47045898f, -0.5559082f, 0.3470459f, -0.41467285f},
    {0.81774902f, -0.6907959f, 0.27453613f, -0.13110352f},
    {1.3527832f, -0.47705078f, 0.088867188f, 0.009765625f},
    {-0.12524414f, -1.1975098f, -0.098266602f, -0.42260742f},
    {1.269043f, -0.45727539f, 0.16687012f, -0.01171875f},
    {1.2557373f, 0.12060547f, -0.23376465f, -0.17541504f},
    {0.9708252f, 0.47338867f, -0.093261719f, -0.39831543f},
    {1.5489502f, -0.4119873f, -0.40942383f, 0.25378418f},
    {0.81066895f, 0.38647461f, 0.028198242f, -0.25500488f},
    {-0.28662109f, -0.89770508f, -0.23730469f, -0.50317383f},
    {1.1340332f, -0.49304199f, 0.23010254f, -0.030029297f},
    {0.56555176f, -0.78161621f, 0.21337891f, -0.19763184f},
    {1.3729248f, -0.50354004f, 0.097900391f, 0.0074462891f},
    {1.1971436f, -0.27880859f, 0.026733398f, 0.027099609f},
    {1.1884766f, -0.1875f, -0.086181641f, 0.057739258f},
    {1.0302734f, -0.41943359f, 0.19067383f, -0.021484375f},
    {1.1361084f, -0.12463379f, -0.10192871f, 0.062133789f},
    {0.20727539f, -1.1016846f, 0.083984375f, -0.37072754f},
    {1.2468262f, -0.34069824f, 0.044921875f, 0.021850586f},
    {1.0241699f, 0.39648438f, -0.092529297f, -0.36486816f},
    {0.87902832f, 0.40478516f, 0.0056152344f, -0.3190918f},
    {-0.010742188f, -0.95324707f, -0.065673828f, -0.5579834f},
    {0.75598145f, -0.63342285f, 0.33691406f, -0.15197754f},
    {1.5045166f, -0.1574707f, -0.40087891f, 0.030883789f},
    {1.5947266f, -0.49743652f, -0.34472656f, 0.22912598f},
    {0.65100098f, 0.36608887f, 0.094604492f, -0.13818359f},
};

/* ---- Configuration and logging ---- */
static const char *env(const char *name) {
    char key[64];
    snprintf(key, sizeof(key), "TLG_%s", name);
    return getenv(key);
}
static int env_flag(const char *name, int fallback) {
    const char *v = env(name);
    return v && *v ? strcmp(v, "0") != 0 : fallback;
}
static int log_enabled(void) {
    static int value = -1;
    if (value < 0) value = env_flag("NGS2_LOG", 0);
    return value;
}
static void note(const char *format, ...) __attribute__((format(printf, 1, 2)));
static void note(const char *format, ...) {
    if (!log_enabled()) return;
    va_list args;
    va_start(args, format);
    fputs("NGS2: ", stdout);
    vprintf(format, args);
    fputc('\n', stdout);
    va_end(args);
}
/* Unknown parameter ids are logged once per (rack id, param id). */
static void note_unknown(uint32_t rack, uint32_t id, uint32_t size) {
    static uint64_t seen[128];
    static unsigned count;
    uint64_t key = (uint64_t)rack << 32 | id;
    for (unsigned i = 0; i < count; ++i) if (seen[i] == key) return;
    if (count < 128) seen[count++] = key;
    note("rack 0x%04x: parameter 0x%08x (%u bytes) stored but not processed", rack, id, size);
}

/* ---- Objects and handles ---- */
static uint32_t rack_kind(uint32_t id) {
    switch (id) {
    case RACK_SAMPLER: return KIND_SAMPLER;
    case RACK_SUBMIXER: return KIND_SUBMIXER;
    case RACK_REVERB: return KIND_REVERB;
    case RACK_MASTERING: return KIND_MASTERING;
    default: return (id & 0xf000) == 0x4000 ? KIND_CUSTOM : KIND_SUBMIXER;
    }
}
static System *as_system(uintptr_t handle) {
    System *s = (System *)handle;
    return s && s->magic == MAGIC_SYSTEM ? s : NULL;
}
static Rack *as_rack(uintptr_t handle) {
    Rack *r = (Rack *)handle;
    return r && r->magic == MAGIC_RACK ? r : NULL;
}
/* A voice handle, or a rack handle meaning its voice 0. */
static Voice *as_voice(uintptr_t handle) {
    if (!handle) return NULL;
    uint32_t magic = *(const uint32_t *)handle;
    if (magic == MAGIC_VOICE) return (Voice *)handle;
    if (magic == MAGIC_RACK) { Rack *r = (Rack *)handle; return r->max_voices ? r->voices[0] : NULL; }
    return NULL;
}
static uintptr_t voice_handle(const Voice *v) { return v->index ? (uintptr_t)v : (uintptr_t)v->rack; }

static void sampler_reset_decoder(Sampler *s) {
    memset(s->hist, 0, sizeof(s->hist));
    s->at9_ok = 0;
    if (s->wave == WAVE_ATRAC9) {
        if (!s->at9) s->at9 = Atrac9GetHandle();
        else { Atrac9ReleaseHandle(s->at9); s->at9 = Atrac9GetHandle(); }
        unsigned char config[4];
        uint32_t c = s->config;
        if ((c & 0xff) == 0xfe) { config[0] = (unsigned char)c; config[1] = (unsigned char)(c >> 8); config[2] = (unsigned char)(c >> 16); config[3] = (unsigned char)(c >> 24); }
        else { config[0] = (unsigned char)(c >> 24); config[1] = (unsigned char)(c >> 16); config[2] = (unsigned char)(c >> 8); config[3] = (unsigned char)c; }
        if (s->at9 && !Atrac9InitDecoder(s->at9, config) && !Atrac9GetCodecInfo(s->at9, &s->at9_info) &&
            s->at9_info.channels > 0 && s->at9_info.channels <= MAX_CH && s->at9_info.frameSamples <= UNIT_FRAMES)
            s->at9_ok = 1;
        else {
            ++stat_errors;
            note("ATRAC9 config %08x rejected", s->config);
        }
    }
    s->at9_frame_in_superframe = 0;
}
static void sampler_clear_blocks(Sampler *s) {
    s->head = s->count = 0;
    s->started = 0;
    s->fifo_len = 1;   /* one silent frame of history before the first sample */
    if (s->fifo) memset(s->fifo, 0, MAX_CH * sizeof(float));
    s->pos = 1.0;
    s->source_done = 0;
    s->empty_renders = 0;
}

static void voice_init(Voice *v, Rack *r, uint32_t index) {
    v->magic = MAGIC_VOICE;
    v->rack = r;
    v->index = index;
    v->channels = r->kind == KIND_SAMPLER ? 1 : MAX_CH;
    for (int p = 0; p < MAX_PORTS; ++p) { v->ports[p].volume = 1.0f; v->ports[p].matrix = -1; }
    v->dry = 0.0f; v->wet = 1.0f;
    v->gain_fbw = v->gain_lfe = 1.0f;
    v->limiter_threshold = 1.0f;
    v->out_channels = MAX_CH;
}
static int voice_alloc_parts(Voice *v) {
    Rack *r = v->rack;
    v->matrices = calloc(r->max_matrices, sizeof(Matrix));
    if (!v->matrices) return 0;
    if (r->kind == KIND_SAMPLER) {
        v->sampler = calloc(1, sizeof(Sampler));
        if (!v->sampler) return 0;
        v->sampler->pitch = 1.0f;
        v->sampler->env_level = 1.0f;
    } else if (!(v->input = calloc((size_t)MAX_CH * MAX_GRAIN, sizeof(float)))) return 0;
    return 1;
}
static void voice_free(Voice *v) {
    if (!v) return;
    if (v->sampler) {
        if (v->sampler->at9) Atrac9ReleaseHandle(v->sampler->at9);
        free(v->sampler->fifo);
        free(v->sampler);
    }
    free(v->matrices);
    free(v->input);
    v->magic = 0;
}

/* Guest allocator: ask for a small context buffer so the game's accounting sees the object.
 * The mixer itself lives in host memory. */
static void guest_alloc(const Allocator *a, BufferInfo *info, uint64_t size) {
    memset(info, 0, sizeof(*info));
    info->host_size = size;
    if (!a || !a->alloc) return;
    info->user_data = a->user_data;
    int32_t r = a->alloc(info);
    if (r) note("guest allocator returned 0x%08x", (uint32_t)r);
}
static void guest_free(const Allocator *a, BufferInfo *info) {
    if (a && a->free && info->host_buffer) a->free(info);
}

#define CONTEXT_BUFFER_SIZE 0x1000

/* ---- Exports: system ---- */
static ABI int32_t ngs2_system_create(const uint8_t *option, const Allocator *allocator, uintptr_t *out) {
    if (!out) return NGS2_ERR_ARG;
    System *s = calloc(1, sizeof(*s));
    if (!s) return NGS2_ERR_MEMORY;
    s->magic = MAGIC_SYSTEM;
    s->grain = 256; s->max_grain = 512; s->rate = 48000;
    if (option) {
        uint32_t v;
        memcpy(&v, option + 0x1c, 4); if (v) s->max_grain = v;
        memcpy(&v, option + 0x20, 4); if (v) s->grain = v;
        memcpy(&v, option + 0x24, 4); if (v) s->rate = v;
    }
    if (s->grain > MAX_GRAIN) s->grain = MAX_GRAIN;
    if (allocator) { s->allocator = *allocator; guest_alloc(allocator, &s->buffer, CONTEXT_BUFFER_SIZE); s->allocated = 1; }
    pthread_mutex_lock(&lock);
    s->next = systems; systems = s;
    pthread_mutex_unlock(&lock);
    static int announced;
    if (!announced++) printf("NGS2: built-in mixer (grain %u, %u Hz)\n", s->grain, s->rate);
    if (!wav) {
        const char *path = env("NGS2_WAV");
        if (path && *path && (wav = fopen(path, "wb"))) { static const char zero[44]; fwrite(zero, 1, 44, wav); }
    }
    *out = (uintptr_t)s;
    return NGS2_OK;
}

static void rack_release(Rack *r) {
    for (uint32_t i = 0; i < r->max_voices; ++i) {
        voice_free(r->voices[i]);
        if (i) free(r->voices[i]);
    }
    free(r->voices[0]);
    free(r->voices);
}
static void unpatch_all(System *s, const Rack *gone) {
    for (Rack *r = s->racks; r; r = r->next)
        for (uint32_t i = 0; i < r->max_voices; ++i)
            for (int p = 0; p < MAX_PORTS; ++p)
                if (r->voices[i]->ports[p].dest && r->voices[i]->ports[p].dest->rack == gone) r->voices[i]->ports[p].dest = NULL;
}

static ABI int32_t ngs2_system_destroy(uintptr_t handle, BufferInfo *out) {
    pthread_mutex_lock(&lock);
    System *s = as_system(handle);
    if (!s) { pthread_mutex_unlock(&lock); return NGS2_ERR_HANDLE; }
    for (System **p = &systems; *p; p = &(*p)->next) if (*p == s) { *p = s->next; break; }
    while (s->racks) { Rack *r = s->racks; s->racks = r->next; rack_release(r); r->magic = 0; free(r); }
    if (out) *out = s->buffer;
    if (s->allocated) guest_free(&s->allocator, &s->buffer);
    s->magic = 0;
    free(s);
    pthread_mutex_unlock(&lock);
    return NGS2_OK;
}

/* ---- Exports: racks ---- */
static ABI int32_t ngs2_query_buffer(uint32_t rack_id, const void *option, BufferInfo *out) {
    (void)rack_id; (void)option;
    if (!out) return NGS2_ERR_ARG;
    memset(out, 0, sizeof(*out));
    out->host_size = CONTEXT_BUFFER_SIZE;
    return NGS2_OK;
}

static int32_t rack_create(uintptr_t system, uint32_t rack_id, const uint8_t *option, const BufferInfo *buffer,
                           const Allocator *allocator, uintptr_t *out) {
    if (!out) return NGS2_ERR_ARG;
    pthread_mutex_lock(&lock);
    System *s = as_system(system);
    if (!s) { pthread_mutex_unlock(&lock); return NGS2_ERR_HANDLE; }
    Rack *r = calloc(1, sizeof(*r));
    if (!r) { pthread_mutex_unlock(&lock); return NGS2_ERR_MEMORY; }
    r->magic = MAGIC_RACK;
    r->system = s;
    r->id = rack_id;
    r->kind = rack_kind(rack_id);
    r->max_voices = r->kind == KIND_SAMPLER ? 256 : 1;
    r->max_ports = r->kind == KIND_SAMPLER ? 8 : 4;
    r->max_matrices = 1;
    if (option) {
        uint32_t v;
        memcpy(&v, option + 0x20, 4); if (v) r->max_voices = v;
        memcpy(&v, option + 0x28, 4); if (v) r->max_matrices = v;
        memcpy(&v, option + 0x2c, 4); if (v) r->max_ports = v;
    }
    if (r->max_voices > 4096) r->max_voices = 4096;
    if (r->max_ports > MAX_PORTS) r->max_ports = MAX_PORTS;
    if (r->max_matrices > MAX_MATRICES) r->max_matrices = MAX_MATRICES;
    r->voices = calloc(r->max_voices, sizeof(Voice *));
    int ok = r->voices != NULL;
    for (uint32_t i = 0; ok && i < r->max_voices; ++i) {
        r->voices[i] = calloc(1, sizeof(Voice));
        if (!r->voices[i]) { ok = 0; break; }
        voice_init(r->voices[i], r, i);
        ok = voice_alloc_parts(r->voices[i]);
    }
    if (!ok) {
        if (r->voices) for (uint32_t i = 0; i < r->max_voices; ++i) if (r->voices[i]) { voice_free(r->voices[i]); free(r->voices[i]); }
        free(r->voices); free(r);
        pthread_mutex_unlock(&lock);
        return NGS2_ERR_MEMORY;
    }
    if (buffer) r->buffer = *buffer;
    if (allocator) { r->allocator = *allocator; guest_alloc(allocator, &r->buffer, CONTEXT_BUFFER_SIZE); r->allocated = 1; }
    /* Appended: creation order is a reasonable tie-break for the render order. */
    Rack **tail = &s->racks;
    while (*tail) tail = &(*tail)->next;
    *tail = r;
    pthread_mutex_unlock(&lock);
    note("rack 0x%04x created: %u voices, %u ports, %u matrices", rack_id, r->max_voices, r->max_ports, r->max_matrices);
    *out = (uintptr_t)r;
    return NGS2_OK;
}
static ABI int32_t ngs2_rack_create(uintptr_t system, uint32_t rack_id, const uint8_t *option, const BufferInfo *buffer, uintptr_t *out) {
    return rack_create(system, rack_id, option, buffer, NULL, out);
}
static ABI int32_t ngs2_rack_create_alloc(uintptr_t system, uint32_t rack_id, const uint8_t *option, const Allocator *allocator, uintptr_t *out) {
    return rack_create(system, rack_id, option, NULL, allocator, out);
}
static ABI int32_t ngs2_rack_destroy(uintptr_t handle, BufferInfo *out) {
    pthread_mutex_lock(&lock);
    Rack *r = as_rack(handle);
    if (!r) { pthread_mutex_unlock(&lock); return NGS2_ERR_HANDLE; }
    System *s = r->system;
    for (Rack **p = &s->racks; *p; p = &(*p)->next) if (*p == r) { *p = r->next; break; }
    unpatch_all(s, r);
    if (out) *out = r->buffer;
    if (r->allocated) guest_free(&r->allocator, &r->buffer);
    rack_release(r);
    r->magic = 0;
    free(r);
    pthread_mutex_unlock(&lock);
    return NGS2_OK;
}
static ABI int32_t ngs2_voice_handle(uintptr_t rack, uint32_t index, uintptr_t *out) {
    Rack *r = as_rack(rack);
    if (!r || !out) return NGS2_ERR_HANDLE;
    if (index >= r->max_voices) return NGS2_ERR_ARG;
    *out = voice_handle(r->voices[index]);
    return NGS2_OK;
}

/* ---- Voice control ---- */
static uint32_t u32_at(const ParamHeader *p, uint32_t offset) {
    uint32_t v = 0;
    if (offset + 4 <= p->size) memcpy(&v, (const uint8_t *)p + offset, 4);
    return v;
}
static float f32_at(const ParamHeader *p, uint32_t offset) {
    float v = 0.0f;
    if (offset + 4 <= p->size) memcpy(&v, (const uint8_t *)p + offset, 4);
    return v;
}
static uintptr_t ptr_at(const ParamHeader *p, uint32_t offset) {
    uintptr_t v = 0;
    if (offset + 8 <= p->size) memcpy(&v, (const uint8_t *)p + offset, 8);
    return v;
}

static void voice_finish(Voice *v) {
    if (v->state == ST_PLAYING) ++stat_finished;
    v->state = ST_FREE;
    v->paused = 0;
    if (v->sampler) {
        sampler_clear_blocks(v->sampler);
        v->sampler->releasing = 0;
    }
}

static void envelope_start(Sampler *s) {
    s->env_segment = 0;
    s->env_position = 0;
    s->releasing = 0;
    s->env_start = s->env_level = s->env_forward ? 0.0f : 1.0f;
}
static void voice_event(Voice *v, uint32_t event) {
    switch (event) {
    case EV_PLAY:
        if (v->state == ST_FREE && v->sampler) break;          /* no waveform set up */
        v->stopped = 0;
        if (v->state != ST_PLAYING) {
            v->state = ST_PLAYING;
            v->paused = 0;
            if (v->sampler) { envelope_start(v->sampler); ++stat_plays; }
        }
        break;
    case EV_RELEASE:
        if (!v->sampler) v->stopped = 1;
        if (v->state != ST_PLAYING) { if (v->state == ST_READY && v->sampler) voice_finish(v); break; }
        if (v->sampler && v->sampler->env_release) {
            Sampler *s = v->sampler;
            s->releasing = 1;
            s->env_segment = s->env_forward;
            s->env_position = 0;
            s->env_start = s->env_level;
        } else voice_finish(v);
        break;
    case EV_STOP:
    case EV_KILL:
        voice_finish(v);
        if (!v->sampler) { v->state = ST_READY; v->stopped = 1; } /* buses stay set up */
        break;
    case EV_PAUSE: if (v->state == ST_PLAYING) v->paused = 1; break;
    case EV_RESUME: v->paused = 0; break;
    default: note("unknown event %u", event); break;
    }
}

static void sampler_setup(Voice *v, const ParamHeader *p) {
    Sampler *s = v->sampler;
    s->wave = u32_at(p, 8);
    s->wave_channels = u32_at(p, 12);
    s->rate = u32_at(p, 16);
    s->config = u32_at(p, 20);
    if (s->wave_channels > MAX_CH) s->wave_channels = MAX_CH;
    if (!s->rate) s->rate = v->rack->system->rate;
    v->channels = s->wave_channels ? s->wave_channels : 1;
    s->pitch = 1.0f;
    s->env_forward = s->env_release = 0;
    s->env_level = 1.0f;
    s->releasing = 0;
    s->decoded_samples = s->decoded_bytes = s->user = 0;
    s->waveform_pointer = NULL;
    v->paused = 0;
    if (!s->fifo) s->fifo = calloc((size_t)FIFO_FRAMES * MAX_CH, sizeof(float));
    sampler_clear_blocks(s);
    sampler_reset_decoder(s);
    v->state = s->wave && s->wave_channels && s->fifo ? ST_READY : ST_FREE;
    if (s->wave && s->wave != WAVE_VAG && s->wave != WAVE_ATRAC9 && (s->wave < WAVE_PCM_U8 || s->wave > WAVE_PCM_F64B)) {
        static uint32_t seen[16]; static unsigned n;
        int known = 0;
        for (unsigned i = 0; i < n; ++i) known |= seen[i] == s->wave;
        if (!known && n < 16) { seen[n++] = s->wave; printf("NGS2: waveform type 0x%x not supported (silent)\n", s->wave); }
    }
}
static void sampler_add_blocks(Voice *v, const ParamHeader *p) {
    Sampler *s = v->sampler;
    const uint8_t *data = (const uint8_t *)ptr_at(p, 8);
    uint32_t flags = u32_at(p, 16), count = u32_at(p, 20);
    const GuestBlock *blocks = (const GuestBlock *)ptr_at(p, 24);
    (void)flags;
    if (!data || !blocks) return;
    if (s->source_done && s->count == 0) s->source_done = 0;  /* more data for a starved stream */
    for (uint32_t i = 0; i < count && i < MAX_BLOCKS; ++i) {
        if (s->count == MAX_BLOCKS) { note("waveform block queue full"); break; }
        Block *b = &s->blocks[(s->head + s->count) % MAX_BLOCKS];
        b->data = data + blocks[i].data_offset;
        b->size = blocks[i].data_size;
        b->repeats = blocks[i].repeats;
        b->skip = blocks[i].skip;
        b->samples = blocks[i].samples;
        b->user = blocks[i].user_data;
        ++s->count;
        ++stat_blocks;
    }
}
static void sampler_envelope(Voice *v, const ParamHeader *p) {
    Sampler *s = v->sampler;
    uint32_t forward = u32_at(p, 8), release = u32_at(p, 12);
    const EnvPoint *points = (const EnvPoint *)ptr_at(p, 16);
    if (!points || forward + release == 0) { s->env_forward = s->env_release = 0; if (!s->releasing) s->env_level = 1.0f; return; }
    if (forward > MAX_ENV) forward = MAX_ENV;
    if (forward + release > MAX_ENV) release = MAX_ENV - forward;
    memcpy(s->env, points, (forward + release) * sizeof(EnvPoint));
    s->env_forward = forward;
    s->env_release = release;
    if (v->state != ST_PLAYING) envelope_start(s);
}
static void store_filter(Voice *v, const ParamHeader *p) {
    uint32_t index = u32_at(p, 8);
    if (index >= MAX_FILTERS) return;
    Filter *f = &v->filters[index];
    f->index = index; f->location = u32_at(p, 12); f->type = u32_at(p, 16); f->mask = u32_at(p, 20);
    f->a = f32_at(p, 24); f->b = f32_at(p, 28); f->c = f32_at(p, 32); f->d = f32_at(p, 36); f->e = f32_at(p, 40);
    if (index >= v->num_filters) v->num_filters = index + 1;
}
static void store_user_fx(Voice *v, const ParamHeader *p) {
    v->user_fx = (UserFxHandler)ptr_at(p, 8);
    v->user_fx_data[0] = ptr_at(p, 16);
    v->user_fx_data[1] = ptr_at(p, 24);
    v->user_fx_data[2] = ptr_at(p, 32);
}

static void apply_param(Voice *v, const ParamHeader *p) {
    Rack *r = v->rack;
    switch (p->id) {
    case 0x1: { /* MATRIX_LEVELS: matrix, count, levels */
        uint32_t m = u32_at(p, 8), count = u32_at(p, 12);
        const float *levels = (const float *)ptr_at(p, 16);
        if (m >= r->max_matrices) return;
        if (count > MAX_LEVELS) count = MAX_LEVELS;
        v->matrices[m].count = levels ? count : 0;
        if (levels && count) memcpy(v->matrices[m].level, levels, count * sizeof(float));
        return;
    }
    case 0x2: { uint32_t port = u32_at(p, 8); if (port < MAX_PORTS) v->ports[port].volume = f32_at(p, 12); return; }
    case 0x3: { uint32_t port = u32_at(p, 8); if (port < MAX_PORTS) v->ports[port].matrix = (int32_t)u32_at(p, 12); return; }
    case 0x4: { uint32_t port = u32_at(p, 8); if (port < MAX_PORTS) v->ports[port].delay = u32_at(p, 12); return; }
    case 0x5: { /* PATCH: port, dest input, dest handle (voice or rack = voice 0; 0 = unpatch) */
        uint32_t port = u32_at(p, 8);
        if (port >= MAX_PORTS) return;
        uintptr_t dest = ptr_at(p, 16);
        Voice *d = dest ? as_voice(dest) : NULL;
        if (dest && (!d || !d->input)) { note("patch to unknown handle %#lx ignored", (unsigned long)dest); d = NULL; }
        v->ports[port].dest = d;
        v->ports[port].input = u32_at(p, 12);
        return;
    }
    case 0x6: voice_event(v, u32_at(p, 8)); return;
    case 0x7:
        v->callback = (CallbackHandler)ptr_at(p, 8);
        v->callback_data = ptr_at(p, 16);
        v->callback_flags = u32_at(p, 24);
        return;
    }
    if (v->sampler) {
        Sampler *s = v->sampler;
        switch (p->id) {
        case 0x10000000: sampler_setup(v, p); return;
        case 0x10000001: sampler_add_blocks(v, p); return;
        case 0x10000004: /* EXIT_LOOP */
            for (uint32_t i = 0; i < s->count; ++i) s->blocks[(s->head + i) % MAX_BLOCKS].repeats = 0;
            return;
        case 0x10000005: { float ratio = f32_at(p, 8); if (ratio >= 0.0f && ratio < 64.0f) s->pitch = ratio; return; }
        case 0x10000006: sampler_envelope(v, p); return;
        case 0x10000008: store_user_fx(v, p); return;
        case 0x1000000a: store_filter(v, p); return;
        case 0x10000002: case 0x10000003: case 0x10000007: case 0x10000009: case 0x1000000b:
            return; /* waveform address, frame offset, distortion, peak meter, filter count */
        }
    } else {
        switch (p->id) {
        case 0x20000000: case 0x30000000:
            v->channels = u32_at(p, 8);
            if (!v->channels || v->channels > MAX_CH) v->channels = MAX_CH;
            if (v->state == ST_FREE) v->state = ST_READY;
            return;
        case 0x20000002: for (int i = 0; i < 8; ++i) v->compressor[i] = f32_at(p, 8 + 4 * (uint32_t)i); return;
        case 0x20000004: store_user_fx(v, p); return;
        case 0x20000006: store_filter(v, p); return;
        case 0x20000001: case 0x20000003: case 0x20000005: case 0x20000007: return;
        case 0x20010000:
            v->channels = u32_at(p, 8);
            v->out_channels = u32_at(p, 12);
            if (!v->channels || v->channels > MAX_CH) v->channels = MAX_CH;
            if (!v->out_channels || v->out_channels > MAX_CH) v->out_channels = MAX_CH;
            if (v->state == ST_FREE) v->state = ST_READY;
            return;
        case 0x20010001:
            v->wet = f32_at(p, 8);
            v->dry = f32_at(p, 12);
            for (int i = 0; i < 24 && 8 + 4 * i + 4 <= p->size; ++i) v->reverb[i] = f32_at(p, 8 + 4 * (uint32_t)i);
            return;
        case 0x30000003: v->limiter = u32_at(p, 8); v->limiter_threshold = f32_at(p, 12); return;
        case 0x30000004: v->gain_fbw = f32_at(p, 8); v->gain_lfe = f32_at(p, 12); return;
        case 0x30000005: v->output_id = u32_at(p, 8); return;
        case 0x30000001: case 0x30000002: case 0x30000006: return;
        }
        if (r->kind == KIND_CUSTOM && (p->id & 0xffff0000) == 0x40020000) {
            v->channels = u32_at(p, 8);
            v->out_channels = u32_at(p, 12);
            if (!v->channels || v->channels > MAX_CH) v->channels = MAX_CH;
            if (!v->out_channels || v->out_channels > MAX_CH) v->out_channels = MAX_CH;
            if (v->state == ST_FREE) v->state = ST_READY;
            return;
        }
        if (r->kind == KIND_CUSTOM && (p->id & 0xff000000) == 0x40000000) {
            uint32_t n = p->size < sizeof(v->custom) ? p->size : sizeof(v->custom);
            memcpy(v->custom, p, n); /* chorus 0x40001c00, delay 0x40001d00, ... (stage 5) */
            return;
        }
    }
    note_unknown(r->id, p->id, p->size);
}

static ABI int32_t ngs2_voice_control(uintptr_t handle, const ParamHeader *params) {
    pthread_mutex_lock(&lock);
    Voice *v = as_voice(handle);
    if (!v) { pthread_mutex_unlock(&lock); return NGS2_ERR_HANDLE; }
    const uint8_t *p = (const uint8_t *)params;
    for (int guard = 0; p && guard < 256; ++guard) {
        const ParamHeader *h = (const ParamHeader *)p;
        if (h->size >= sizeof(ParamHeader)) apply_param(v, h);
        if (!h->next) break;
        p += h->next;
    }
    pthread_mutex_unlock(&lock);
    return NGS2_OK;
}

static uint32_t voice_flags(const Voice *v) {
    switch (v->state) {
    case ST_READY: return FLAG_INUSE;
    case ST_PLAYING: {
        uint32_t f = FLAG_INUSE | FLAG_PLAYING;
        if (v->paused) f |= FLAG_PAUSED;
        if (v->sampler && v->sampler->source_done && !v->sampler->releasing) f |= FLAG_EMPTY;
        return f;
    }
    default: return 0;
    }
}
static ABI int32_t ngs2_voice_state(uintptr_t handle, void *out, uint64_t size) {
    if (!out) return NGS2_ERR_ARG;
    pthread_mutex_lock(&lock);
    Voice *v = as_voice(handle);
    if (!v) { pthread_mutex_unlock(&lock); return NGS2_ERR_HANDLE; }
    uint8_t state[0x60];
    memset(state, 0, sizeof(state));
    uint32_t flags = voice_flags(v);
    memcpy(state, &flags, 4);
    if (v->sampler) {
        const Sampler *s = v->sampler;
        float env_height = s->env_level, peak = v->peak;
        uint64_t data = (uint64_t)(uintptr_t)s->waveform_pointer;
        memcpy(state + 4, &env_height, 4);
        memcpy(state + 8, &peak, 4);
        memcpy(state + 0x10, &s->decoded_samples, 8);
        memcpy(state + 0x18, &s->decoded_bytes, 8);
        memcpy(state + 0x20, &s->user, 8);
        memcpy(state + 0x28, &data, 8);
    } else if (v->rack->kind == KIND_MASTERING) {
        float peak = v->peak;
        memcpy(state + 4, &peak, 4);
    } else {
        float one = 1.0f, peak = v->peak;
        memcpy(state + 4, &one, 4);
        memcpy(state + 8, &peak, 4);
        memcpy(state + 12, &one, 4);
    }
    memcpy(out, state, size < sizeof(state) ? size : sizeof(state));
    pthread_mutex_unlock(&lock);
    return NGS2_OK;
}

/* ---- Decoding ---- */
static float pcm_sample(uint32_t wave, const uint8_t *p) {
    switch (wave) {
    case WAVE_PCM_U8: return ((float)p[0] - 128.0f) / 128.0f;
    case WAVE_PCM_I8: return (float)(int8_t)p[0] / 128.0f;
    case WAVE_PCM_I16L: return (float)(int16_t)(p[0] | p[1] << 8) / 32768.0f;
    case WAVE_PCM_I16B: return (float)(int16_t)(p[1] | p[0] << 8) / 32768.0f;
    case WAVE_PCM_I24L: return (float)((int32_t)((uint32_t)p[0] << 8 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 24) >> 8) / 8388608.0f;
    case WAVE_PCM_I24B: return (float)((int32_t)((uint32_t)p[2] << 8 | (uint32_t)p[1] << 16 | (uint32_t)p[0] << 24) >> 8) / 8388608.0f;
    case WAVE_PCM_I32L: return (float)(int32_t)((uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24) / 2147483648.0f;
    case WAVE_PCM_I32B: return (float)(int32_t)((uint32_t)p[3] | (uint32_t)p[2] << 8 | (uint32_t)p[1] << 16 | (uint32_t)p[0] << 24) / 2147483648.0f;
    case WAVE_PCM_F32L: { float f; memcpy(&f, p, 4); return f; }
    case WAVE_PCM_F32B: { uint8_t b[4] = {p[3], p[2], p[1], p[0]}; float f; memcpy(&f, b, 4); return f; }
    case WAVE_PCM_F64L: { double d; memcpy(&d, p, 8); return (float)d; }
    case WAVE_PCM_F64B: { uint8_t b[8] = {p[7], p[6], p[5], p[4], p[3], p[2], p[1], p[0]}; double d; memcpy(&d, b, 8); return (float)d; }
    }
    return 0.0f;
}
static uint32_t pcm_bytes(uint32_t wave) {
    static const uint8_t sizes[] = {1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 8, 8};
    return wave >= WAVE_PCM_U8 && wave <= WAVE_PCM_F64B ? sizes[wave - WAVE_PCM_U8] : 0;
}

/* One VAG/HEVAG frame (16 bytes, 28 samples) of one channel. Indexes above 4 are HEVAG's
 * extended predictors; flag 7 marks an empty frame. */
static void vag_frame(const uint8_t *frame, float hist[4], float *out, uint32_t stride) {
    uint32_t index = (uint32_t)(frame[0] >> 4) | (frame[1] & 0xf0u), shift = frame[0] & 0xfu, flag = frame[1] & 0xfu;
    if (index > 127) index = 0;
    const float *c = hevag_coefs[index];
    for (uint32_t i = 0; i < 28; ++i) {
        float sample = 0.0f;
        if (flag != 7) {
            int code = (i & 1) ? frame[2 + i / 2] >> 4 : frame[2 + i / 2] & 0xf;
            if (code >= 8) code -= 16;
            sample = (float)((code * 4096) >> shift) + hist[0] * c[0] + hist[1] * c[1] + hist[2] * c[2] + hist[3] * c[3];
        }
        hist[3] = hist[2]; hist[2] = hist[1]; hist[1] = hist[0]; hist[0] = sample;
        float v = sample / 32768.0f;
        out[i * stride] = v > 1.0f ? 1.0f : v < -1.0f ? -1.0f : v;
    }
}

/* Appends decoded frames to the FIFO, dropping the block's skip samples and clipping to its
 * sample count. */
static void fifo_push(Sampler *s, uint32_t channels, const float *frames, uint32_t count) {
    if (s->skip_left) {
        uint32_t drop = s->skip_left < count ? s->skip_left : count;
        s->skip_left -= drop;
        frames += (size_t)drop * MAX_CH;
        count -= drop;
    }
    if (count > s->out_left) count = s->out_left;
    s->out_left -= count;
    if (s->fifo_len + count > FIFO_FRAMES) count = FIFO_FRAMES - s->fifo_len;
    float *dst = s->fifo + (size_t)s->fifo_len * MAX_CH;
    for (uint32_t i = 0; i < count; ++i) for (uint32_t c = 0; c < MAX_CH; ++c) dst[i * MAX_CH + c] = c < channels ? frames[i * MAX_CH + c] : 0.0f;
    s->fifo_len += count;
    s->decoded_samples += count;
}

static void block_begin(Sampler *s, const Block *b, int restart) {
    s->byte = 0;
    s->skip_left = b->skip;
    s->out_left = b->samples ? b->samples : UINT32_MAX;
    s->started = 1;
    if (!restart) s->repeated = 0;
    if (s->wave == WAVE_ATRAC9 && (restart || b->skip)) sampler_reset_decoder(s);
    s->at9_frame_in_superframe = 0;
    s->at9_superframe_start = 0;
    s->user = b->user;
    s->waveform_pointer = b->data;
}
/* The block finished: repeat it or move on. Calls the voice callback when one is set. */
static void block_end(Voice *v) {
    Sampler *s = v->sampler;
    Block *b = &s->blocks[s->head];
    int repeat = b->repeats != 0;
    if (v->callback && (v->callback_flags & (repeat ? 2u : 1u))) {
        CallbackInfo info = {v->callback_data, voice_handle(v), repeat ? 2u : 1u, 0, b->user, b->data, b->size, s->repeated, 0, 0};
        v->callback(&info);
    }
    if (repeat) {
        if (b->repeats != UINT32_MAX) --b->repeats;
        ++s->repeated;
        block_begin(s, b, 1);
        return;
    }
    s->head = (s->head + 1) % MAX_BLOCKS;
    --s->count;
    s->started = 0;
}

/* Decodes one unit (PCM chunk, one VAG frame per channel, one ATRAC9 frame) of the current
 * block. Returns 0 when the queue is empty. */
static int decode_unit(Voice *v) {
    Sampler *s = v->sampler;
    if (!s->count) return 0;
    Block *b = &s->blocks[s->head];
    if (!s->started) block_begin(s, b, 0);
    const uint32_t ch = s->wave_channels;
    float frames[UNIT_FRAMES * MAX_CH];
    uint32_t produced = 0, used = 0;
    if (!s->out_left) { block_end(v); return 1; }
    if (s->wave == WAVE_VAG) {
        uint32_t group = 16 * ch;
        if (s->byte + group <= b->size) {
            for (uint32_t c = 0; c < ch; ++c) vag_frame(b->data + s->byte + 16 * c, s->hist[c], frames + c, MAX_CH);
            produced = 28; used = group;
        }
    } else if (s->wave == WAVE_ATRAC9) {
        const Atrac9CodecInfo *info = &s->at9_info;
        if (s->at9_ok && s->byte < b->size) {
            int16_t pcm[UNIT_FRAMES * MAX_CH];
            int bytes = 0;
            if (Atrac9Decode(s->at9, b->data + s->byte, pcm, &bytes) || bytes <= 0) {
                ++stat_errors;
                note("ATRAC9 decode error at byte %u of a %u-byte block", s->byte, b->size);
                s->byte = b->size;
            } else {
                uint32_t n = (uint32_t)info->frameSamples, c_in = (uint32_t)info->channels;
                for (uint32_t i = 0; i < n; ++i)
                    for (uint32_t c = 0; c < MAX_CH; ++c) frames[i * MAX_CH + c] = c < c_in ? pcm[i * c_in + c] / 32768.0f : 0.0f;
                produced = n;
                used = (uint32_t)bytes;
                if (++s->at9_frame_in_superframe == (uint32_t)info->framesInSuperframe) {
                    s->at9_frame_in_superframe = 0;
                    s->at9_superframe_start += (uint32_t)info->superframeSize;
                    used = s->at9_superframe_start - s->byte; /* skip the superframe padding */
                }
            }
        }
    } else {
        uint32_t bytes = pcm_bytes(s->wave), frame = bytes * ch;
        if (frame && s->byte + frame <= b->size) {
            uint32_t n = (b->size - s->byte) / frame;
            if (n > UNIT_FRAMES) n = UNIT_FRAMES;
            for (uint32_t i = 0; i < n; ++i)
                for (uint32_t c = 0; c < MAX_CH; ++c)
                    frames[i * MAX_CH + c] = c < ch ? pcm_sample(s->wave, b->data + s->byte + i * frame + c * bytes) : 0.0f;
            produced = n; used = n * frame;
        }
    }
    if (!produced) { block_end(v); return 1; }   /* data exhausted before the sample count */
    s->byte += used;
    s->decoded_bytes += used;
    s->waveform_pointer = b->data + s->byte;
    fifo_push(s, ch, frames, produced);
    if (!s->out_left) block_end(v);
    return 1;
}

/* Makes frame `need` available (or marks the source done). */
static void fifo_fill(Voice *v, uint32_t need) {
    Sampler *s = v->sampler;
    while (s->fifo_len <= need && !s->source_done) {
        if (s->fifo_len + UNIT_FRAMES > FIFO_FRAMES) {
            /* Keep one frame of history before the read position. */
            uint32_t drop = (uint32_t)s->pos;
            drop = drop > 1 ? drop - 1 : 0;
            if (!drop) break;
            memmove(s->fifo, s->fifo + (size_t)drop * MAX_CH, (size_t)(s->fifo_len - drop) * MAX_CH * sizeof(float));
            s->fifo_len -= drop;
            s->pos -= drop;
            need -= drop;
            continue;
        }
        if ((s->wave == WAVE_ATRAC9 && !s->at9_ok) || (s->wave != WAVE_VAG && s->wave != WAVE_ATRAC9 && !pcm_bytes(s->wave))) {
            s->count = 0;   /* nothing this mixer can decode: the voice ends */
            s->source_done = 1;
            break;
        }
        if (!decode_unit(v)) s->source_done = 1;
    }
}

static float envelope_next(Sampler *s, int *done) {
    uint32_t end = s->env_forward + (s->releasing ? s->env_release : 0);
    if (!s->env_forward && !s->releasing) return 1.0f;
    while (s->env_segment < end) {
        const EnvPoint *p = &s->env[s->env_segment];
        if (s->env_position < p->duration) {
            float t = (float)s->env_position / (float)p->duration, k;
            switch (p->curve) {
            case 1: k = t * t; break;
            case 2: k = 1.0f - (1.0f - t) * (1.0f - t); break;
            default: k = t; break;
            }
            ++s->env_position;
            s->env_level = s->env_start + (p->height - s->env_start) * k;
            return s->env_level;
        }
        s->env_level = s->env_start = p->height;
        s->env_position = 0;
        ++s->env_segment;
    }
    if (s->releasing) *done = 1;
    return s->env_level;
}

/* Renders `n` frames of a playing sampler voice into planar `out`; returns frames written. */
static uint32_t sampler_render(Voice *v, uint32_t n, float out[MAX_CH][MAX_GRAIN]) {
    Sampler *s = v->sampler;
    const uint32_t ch = v->channels;
    double step = (double)s->pitch * (double)s->rate / (double)v->rack->system->rate;
    if (step > 16.0) step = 16.0;
    uint32_t i = 0;
    int ended = 0;
    for (; i < n; ++i) {
        uint32_t index = (uint32_t)s->pos;
        fifo_fill(v, index + 2);
        index = (uint32_t)s->pos;
        if (index >= s->fifo_len) { ended = 1; break; }
        float t = (float)(s->pos - index);
        const float *f0 = s->fifo + (size_t)(index - 1) * MAX_CH, *f1 = f0 + MAX_CH;
        const float *f2 = index + 1 < s->fifo_len ? f1 + MAX_CH : NULL, *f3 = index + 2 < s->fifo_len ? f1 + 2 * MAX_CH : NULL;
        int done = 0;
        float gain = envelope_next(s, &done);
        for (uint32_t c = 0; c < ch; ++c) {
            float y0 = f0[c], y1 = f1[c], y2 = f2 ? f2[c] : 0.0f, y3 = f3 ? f3[c] : 0.0f;
            /* Catmull-Rom */
            float a = -0.5f * y0 + 1.5f * y1 - 1.5f * y2 + 0.5f * y3;
            float b = y0 - 2.5f * y1 + 2.0f * y2 - 0.5f * y3;
            float c1 = -0.5f * y0 + 0.5f * y2;
            out[c][i] = (((a * t + b) * t + c1) * t + y1) * gain;
        }
        s->pos += step;
        if (done) { ++i; ended = 2; break; }
    }
    for (uint32_t c = 0; c < ch; ++c) for (uint32_t k = i; k < n; ++k) out[c][k] = 0.0f;
    if (ended == 2) voice_finish(v);
    else if (ended == 1 || (s->source_done && (uint32_t)s->pos >= s->fifo_len)) {
        /* Out of data: a stream may still queue blocks for a moment (reported as EMPTY). */
        if (s->count == 0 && ++s->empty_renders > END_GRACE_RENDERS) voice_finish(v);
        else if (s->count) { s->source_done = 0; s->empty_renders = 0; }
        if (v->state != ST_FREE) ++stat_starved;
    } else s->empty_renders = 0;
    return i;
}

/* ---- Mixing ---- */
static void mix_port(const Voice *src, const Port *port, float in[MAX_CH][MAX_GRAIN], uint32_t n) {
    Voice *dst = port->dest;
    if (!dst || !dst->input || port->volume == 0.0f) return;
    uint32_t sc = src->channels, dc = dst->channels;
    const Matrix *m = port->matrix >= 0 && (uint32_t)port->matrix < src->rack->max_matrices && src->matrices[port->matrix].count
                          ? &src->matrices[port->matrix] : NULL;
    for (uint32_t o = 0; o < dc; ++o) {
        float *acc = dst->input + (size_t)o * MAX_GRAIN;
        for (uint32_t i = 0; i < sc; ++i) {
            float level;
            if (m) {
                uint32_t k = o * sc + i;
                level = k < m->count ? m->level[k] : 0.0f;
            } else level = o == i ? 1.0f : 0.0f;
            level *= port->volume;
            if (level == 0.0f) continue;
            const float *x = in[i];
            for (uint32_t k = 0; k < n; ++k) acc[k] += x[k] * level;
        }
    }
    dst->has_input = 1;
}
static void call_user_fx(Voice *v, float data[MAX_CH][MAX_GRAIN], uint32_t n) {
    static int enabled = -1;
    if (enabled < 0) enabled = env_flag("NGS2_USERFX", 1);
    if (!v->user_fx || !enabled) return;
    float *channels[MAX_CH];
    for (int c = 0; c < MAX_CH; ++c) channels[c] = data[c];
    UserFxContext context = {channels, v->user_fx_data[0], v->user_fx_data[1], v->user_fx_data[2], 0, v->channels, n, v->rack->system->rate};
    UserFxHandler handler = v->user_fx;
    ++stat_user_fx;
    /* Guest code may take its own locks while another game thread holding them waits in
     * VoiceControl: run it without the mixer lock. */
    pthread_mutex_unlock(&lock);
    handler(&context);
    pthread_mutex_lock(&lock);
}
static float peak_of(float data[MAX_CH][MAX_GRAIN], uint32_t channels, uint32_t n) {
    float peak = 0.0f;
    for (uint32_t c = 0; c < channels; ++c) for (uint32_t k = 0; k < n; ++k) { float a = fabsf(data[c][k]); if (a > peak) peak = a; }
    return peak;
}

static float scratch[MAX_CH][MAX_GRAIN];
static float outputs[8][MAX_CH][MAX_GRAIN];
static uint32_t output_channels[8];

static void process_sampler(Voice *v, uint32_t n) {
    if (v->state != ST_PLAYING || v->paused) { if (v->state != ST_PLAYING) v->peak = 0.0f; return; }
    uint32_t written = sampler_render(v, n, scratch);
    if (!written) { v->peak = 0.0f; return; }
    call_user_fx(v, scratch, n);
    v->peak = peak_of(scratch, v->channels, n);
    for (uint32_t p = 0; p < v->rack->max_ports; ++p) mix_port(v, &v->ports[p], scratch, n);
}

static void process_bus(Voice *v, uint32_t n) {
    static int reverb_pass = -1, custom_mute = -1;
    if (reverb_pass < 0) { const char *e = env("NGS2_REVERB"); reverb_pass = e && !strcmp(e, "pass"); }
    if (custom_mute < 0) { const char *e = env("NGS2_CUSTOM"); custom_mute = e && !strcmp(e, "mute"); }
    /* The traced games kick every bus; one that was never kicked still passes its input. */
    if ((v->state != ST_PLAYING && v->stopped) || v->paused) { v->peak = 0.0f; return; }
    float (*data)[MAX_GRAIN] = (float (*)[MAX_GRAIN])v->input;
    uint32_t kind = v->rack->kind;
    if (kind == KIND_REVERB && !reverb_pass) {
        for (uint32_t c = 0; c < v->channels; ++c) for (uint32_t k = 0; k < n; ++k) data[c][k] *= v->dry;
        if (v->out_channels > v->channels) for (uint32_t c = v->channels; c < v->out_channels; ++c) memset(data[c], 0, n * sizeof(float));
    } else if (kind == KIND_CUSTOM && custom_mute) {
        for (uint32_t c = 0; c < MAX_CH; ++c) memset(data[c], 0, n * sizeof(float));
    }
    if (kind == KIND_SUBMIXER && v->user_fx) { call_user_fx(v, data, n); v->has_input = 1; }
    uint32_t out_ch = kind == KIND_REVERB || kind == KIND_CUSTOM ? v->out_channels : v->channels;
    if (kind == KIND_MASTERING) {
        for (uint32_t c = 0; c < v->channels; ++c) {
            float g = c == 3 ? v->gain_lfe : v->gain_fbw;
            for (uint32_t k = 0; k < n; ++k) {
                float x = data[c][k] * g;
                if (v->limiter) { float t = v->limiter_threshold > 0.0f ? v->limiter_threshold : 1.0f; x = x > t ? t : x < -t ? -t : x; }
                data[c][k] = x;
            }
        }
        v->peak = peak_of(data, v->channels, n);
        uint32_t o = v->output_id < 8 ? v->output_id : 0;
        for (uint32_t c = 0; c < v->channels; ++c) for (uint32_t k = 0; k < n; ++k) outputs[o][c][k] += data[c][k];
        if (v->channels > output_channels[o]) output_channels[o] = v->channels;
        return;
    }
    v->peak = peak_of(data, out_ch, n);
    uint32_t saved = v->channels;
    v->channels = out_ch;   /* ports see the bus output width */
    for (uint32_t p = 0; p < v->rack->max_ports; ++p) {
        if (v->ports[p].dest == v) continue;
        mix_port(v, &v->ports[p], data, n);
    }
    v->channels = saved;
}

/* Buses in dependency order: a bus runs once every bus patched into it has run. */
static void render_buses(System *s, uint32_t n) {
    for (Rack *r = s->racks; r; r = r->next) {
        if (r->kind == KIND_SAMPLER) continue;
        for (uint32_t i = 0; i < r->max_voices; ++i) { r->voices[i]->pending = 0; r->voices[i]->visited = 0; }
    }
    for (Rack *r = s->racks; r; r = r->next) {
        if (r->kind == KIND_SAMPLER) continue;
        for (uint32_t i = 0; i < r->max_voices; ++i) {
            Voice *v = r->voices[i];
            for (uint32_t p = 0; p < r->max_ports; ++p) if (v->ports[p].dest && v->ports[p].dest != v) ++v->ports[p].dest->pending;
        }
    }
    int progress = 1;
    while (progress) {
        progress = 0;
        Voice *blocked = NULL;
        for (Rack *r = s->racks; r; r = r->next) {
            if (r->kind == KIND_SAMPLER) continue;
            for (uint32_t i = 0; i < r->max_voices; ++i) {
                Voice *v = r->voices[i];
                if (v->visited) continue;
                if (v->pending) { if (!blocked) blocked = v; continue; }
                v->visited = 1;
                process_bus(v, n);
                for (uint32_t p = 0; p < r->max_ports; ++p) if (v->ports[p].dest && v->ports[p].dest != v && v->ports[p].dest->pending) --v->ports[p].dest->pending;
                progress = 1;
            }
        }
        if (!progress && blocked) {   /* a patch cycle: break it at the first waiting bus */
            static int warned;
            if (!warned++) printf("NGS2: patch cycle between buses; processing in creation order\n");
            blocked->pending = 0;
            progress = 1;
        }
    }
}

static void write_output(const RenderBuffer *b, uint32_t index, uint32_t n) {
    if (!b->buffer || !b->channels) return;
    uint32_t bytes = b->waveform == WAVE_PCM_I16L ? 2 : b->waveform == WAVE_PCM_F32L ? 4 : 0;
    memset(b->buffer, 0, b->size);
    if (!bytes) return;
    uint64_t frames = b->size / ((uint64_t)bytes * b->channels);
    if (frames > n) frames = n;
    const uint32_t src_ch = index < 8 ? output_channels[index] : 0;
    for (uint64_t k = 0; k < frames; ++k)
        for (uint32_t c = 0; c < b->channels; ++c) {
            float x = 0.0f;
            if (src_ch) x = outputs[index][c < src_ch ? c : 0][k];
            if (c >= src_ch && src_ch != 1) x = 0.0f;   /* mono output feeds every channel */
            if (bytes == 4) ((float *)b->buffer)[k * b->channels + c] = x;
            else {
                float y = x * 32768.0f;
                ((int16_t *)b->buffer)[k * b->channels + c] = (int16_t)(y > 32767.0f ? 32767.0f : y < -32768.0f ? -32768.0f : y);
            }
        }
}

static void wav_update(void) {
    uint32_t ch = wav_channels ? wav_channels : 8, rate = 48000, fmt_size = 16, data = (uint32_t)(wav_frames * ch * 4), riff = 36 + data;
    uint32_t byte_rate = rate * ch * 4;
    uint16_t format = 3, channels = (uint16_t)ch, align = (uint16_t)(ch * 4), bits = 32;
    long here = ftell(wav);
    fseek(wav, 0, SEEK_SET);
    fwrite("RIFF", 1, 4, wav); fwrite(&riff, 4, 1, wav); fwrite("WAVEfmt ", 1, 8, wav);
    fwrite(&fmt_size, 4, 1, wav); fwrite(&format, 2, 1, wav); fwrite(&channels, 2, 1, wav); fwrite(&rate, 4, 1, wav);
    fwrite(&byte_rate, 4, 1, wav); fwrite(&align, 2, 1, wav); fwrite(&bits, 2, 1, wav);
    fwrite("data", 1, 4, wav); fwrite(&data, 4, 1, wav);
    fseek(wav, here, SEEK_SET);
    fflush(wav);
}

static void summary(const System *s) {
    unsigned playing = 0, ready = 0;
    for (const Rack *r = s->racks; r; r = r->next)
        if (r->kind == KIND_SAMPLER)
            for (uint32_t i = 0; i < r->max_voices; ++i) { playing += r->voices[i]->state == ST_PLAYING; ready += r->voices[i]->state == ST_READY; }
    note("render %llu: %u voices playing, %u ready; %llu plays, %llu finished, %llu blocks, %llu starved renders, %llu user FX calls, %llu errors",
         (unsigned long long)s->renders, playing, ready, (unsigned long long)stat_plays, (unsigned long long)stat_finished,
         (unsigned long long)stat_blocks, (unsigned long long)stat_starved, (unsigned long long)stat_user_fx, (unsigned long long)stat_errors);
}

static ABI int32_t ngs2_render(uintptr_t handle, const RenderBuffer *buffers, uint32_t count) {
    pthread_mutex_lock(&lock);
    System *s = as_system(handle);
    if (!s || (count && !buffers)) { pthread_mutex_unlock(&lock); return NGS2_ERR_HANDLE; }
    uint32_t n = s->grain;
    memset(outputs, 0, sizeof(outputs));
    memset(output_channels, 0, sizeof(output_channels));
    for (Rack *r = s->racks; r; r = r->next) {
        if (r->kind == KIND_SAMPLER) continue;
        for (uint32_t i = 0; i < r->max_voices; ++i) {
            Voice *v = r->voices[i];
            if (v->has_input) { for (int c = 0; c < MAX_CH; ++c) memset(v->input + (size_t)c * MAX_GRAIN, 0, n * sizeof(float)); v->has_input = 0; }
        }
    }
    for (Rack *r = s->racks; r; r = r->next)
        if (r->kind == KIND_SAMPLER)
            for (uint32_t i = 0; i < r->max_voices; ++i) process_sampler(r->voices[i], n);
    render_buses(s, n);
    for (uint32_t i = 0; i < count; ++i) write_output(&buffers[i], i, n);
    if (wav && count && buffers[0].buffer && buffers[0].waveform == WAVE_PCM_F32L && buffers[0].channels) {
        uint64_t frames = buffers[0].size / (4u * buffers[0].channels);
        if (frames > n) frames = n;
        wav_channels = buffers[0].channels;
        fwrite(buffers[0].buffer, 4u * buffers[0].channels, frames, wav);
        wav_frames += frames;
        if (!(s->renders % 500)) wav_update();
    }
    ++s->renders;
    if (log_enabled() && s->rate && !(s->renders % (30u * s->rate / n))) summary(s);
    pthread_mutex_unlock(&lock);
    return NGS2_OK;
}

static const RuntimeExport exports[] = {
    {"sceNgs2SystemCreateWithAllocator", ngs2_system_create}, {"sceNgs2SystemDestroy", ngs2_system_destroy},
    {"sceNgs2SystemRender", ngs2_render}, {"sceNgs2RackQueryBufferSize", ngs2_query_buffer},
    {"sceNgs2RackCreate", ngs2_rack_create}, {"sceNgs2RackCreateWithAllocator", ngs2_rack_create_alloc},
    {"sceNgs2RackDestroy", ngs2_rack_destroy}, {"sceNgs2RackGetVoiceHandle", ngs2_voice_handle},
    {"sceNgs2VoiceControl", ngs2_voice_control}, {"sceNgs2VoiceGetState", ngs2_voice_state},
};

/* TLG_NGS2=native: libSceNgs2.sprx from the console firmware is linked as a module and its
 * exports must win, so nothing resolves here. */
int runtime_ngs2_native(void) {
    static int value = -1;
    if (value < 0) { const char *v = env("NGS2"); value = v && !strcmp(v, "native"); }
    return value;
}
uintptr_t runtime_ngs2_resolve(const char *name) {
    if (runtime_ngs2_native()) return 0;
    return RUNTIME_LOOKUP(exports, name);
}
/* Direct access by symbol name for the offline tests (tests/test_ngs2.c). */
void *runtime_ngs2_function(const char *symbol) {
    for (size_t i = 0; i < sizeof(exports) / sizeof(*exports); ++i)
        if (!strcmp(exports[i].name, symbol)) return exports[i].function;
    return NULL;
}
