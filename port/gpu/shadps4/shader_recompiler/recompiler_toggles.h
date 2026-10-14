// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

// tlg: recompiler switches read from the environment, each read once. The GR2_/ISS_ names reach
// here as TLG_ (the probe aliases the port prefix at start-up).
//
// Shader loop budget, from the Shadow of the Colossus native port
// (github.com/AjncSystem/ShadowOfTheColossus-PC, GPL-2.0, commits 3cfed48d and 3bc854ce): every
// structured loop of a recompiled shader counts its iterations and is left once it runs past a
// budget. A guest loop that terminates on the PS4 but not on the host (stale or garbage data
// from emulation, EXEC/wave64 differences, NaN compares) would otherwise spin until the OS GPU
// watchdog resets the device ("Device lost during submit", Windows TDR). Real content stays far
// below the budgets, so a cut loop only spoils one frame instead of ending the session.

#pragma once

#include <cstdint>
#include <cstdlib>
#include <initializer_list>

namespace Shader::Toggles {

namespace Detail {
/// TLG_<name>=<number> (decimal, 0x hex or 0 octal) when set, otherwise the default.
inline std::uint32_t EnvU32(const char* name, std::uint32_t fallback) {
    const char* v = std::getenv(name);
    if (!v || !*v) {
        return fallback;
    }
    char* end = nullptr;
    const unsigned long long value = std::strtoull(v, &end, 0);
    if (end == v) {
        return fallback;
    }
    return value > 0xffffffffull ? 0xffffffffu : static_cast<std::uint32_t>(value);
}
} // namespace Detail

inline constexpr std::uint32_t DefaultLoopBudget = 1u << 18;
inline constexpr std::uint32_t DefaultPerLoopBudget = 8192u;

/// Total loop iterations one shader invocation may run across all its (nested) loops.
/// TLG_LOOP_LIMIT=<n>; 0 turns every loop budget off (this one and the per-loop one).
inline std::uint32_t LoopBudget() {
    static const std::uint32_t budget = Detail::EnvU32("TLG_LOOP_LIMIT", DefaultLoopBudget);
    return budget;
}

/// Iterations of one loop, counted again from zero each time the loop is entered: a runaway
/// loop stops early, while a shader that runs many short loops one after another only meets
/// the invocation budget. TLG_LOOP_LIMIT_PER_LOOP=<n>; 0 turns only this one off.
inline std::uint32_t PerLoopBudget() {
    static const std::uint32_t budget =
        LoopBudget() == 0 ? 0u : Detail::EnvU32("TLG_LOOP_LIMIT_PER_LOOP", DefaultPerLoopBudget);
    return budget;
}

/// Bits for the shader binary cache version: shaders recompiled under other switches must not
/// be reused (the cache key only hashes the recompiler sources). 0 with the defaults; otherwise
/// a 16-bit hash of the budgets (never 0).
inline std::uint32_t ShaderBinarySalt() {
    const std::uint32_t total = LoopBudget();
    const std::uint32_t own = PerLoopBudget();
    if (total == DefaultLoopBudget && own == DefaultPerLoopBudget) {
        return 0u;
    }
    std::uint32_t h = 2166136261u; // FNV-1a over both values
    for (const std::uint32_t value : {total, own}) {
        for (int shift = 0; shift < 32; shift += 8) {
            h = (h ^ ((value >> shift) & 0xffu)) * 16777619u;
        }
    }
    h = (h ^ (h >> 16)) & 0xffffu;
    return h == 0 ? 1u : h;
}

} // namespace Shader::Toggles
