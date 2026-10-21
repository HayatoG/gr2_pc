// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later
// tlg: 1D images created as 2D images of height 1 (AmdGpu::Image::IsBlock1D).
//
// GR2 keeps its own TLG_BLOCK1D switch for block-coded 1D textures (resource.h, off by default).
// This header only carries the BP09 state from iss_pc.

#pragma once

#include <atomic>

namespace AmdGpu {

// tlg: BP09 (CTR d26bcb2), TLG_BP09=1: every 1D image, block-coded or not, is a 2D image of
// height 1 on the host (Vulkan cannot view a 2D render target as 1D, and games build
// colour-grading LUTs from 64x1 / 1024x1 targets they sample as 1D). Set once by vk_instance.cpp
// before any image or shader exists; part of the shader cache key through the backports salt.
inline std::atomic<bool> all_1d_as_2d{false};

inline bool All1DAs2D() {
    return all_1d_as_2d.load(std::memory_order_relaxed);
}

} // namespace AmdGpu
