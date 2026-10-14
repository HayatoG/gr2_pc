// SPDX-License-Identifier: GPL-2.0-or-later
// Recompiler fixes ported from the SotC native port (recompiler_toggles.h): LDS barriers for
// partial-wave and multi-wave compute workgroups, and S_WQM_B64. No window, no game.
// The switches are read once per process, so run it with their other values too:
//   out/gpu/recompiler-fixes-test [dir]
//   TLG_LDS_SMALL=0 TLG_LDS_MULTI=0 TLG_WQM=0 out/gpu/recompiler-fixes-test
// With [dir], the multi-wave compute shader is written there as SPIR-V (for spirv-val).
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <span>
#include "shader_recompiler/backend/spirv/emit_spirv.h"
#include "shader_recompiler/frontend/translate/translate.h"
#include "shader_recompiler/ir/ir_emitter.h"
#include "shader_recompiler/ir/passes/ir_passes.h"
#include "shader_recompiler/profile.h"
#include "shader_recompiler/recompiler_toggles.h"
#include "shader_recompiler/runtime_info.h"

using namespace Shader;

static int failures = 0;

static void Check(bool ok, const char* what) {
    std::printf("%s: %s\n", ok ? "ok" : "FAIL", what);
    failures += ok ? 0 : 1;
}

static u32 Count(const IR::Block& block, IR::Opcode opcode) {
    u32 count = 0;
    for (const IR::Inst& inst : block.Instructions()) {
        count += inst.GetOpcode() == opcode ? 1 : 0;
    }
    return count;
}

struct BarrierResult {
    u32 workgroup;
    u32 subgroup;
};

// One block: an LDS write, then a read of it (another lane's slot on the guest), then a write.
static BarrierResult RunBarrierPass(u32 threads, const char* spirv_path = nullptr) {
    Info info{};
    info.hw_stage = HwStage::Compute;
    info.sw_stage = SwStage::Compute;
    RuntimeInfo runtime{};
    runtime.Initialize(HwStage::Compute, SwStage::Compute);
    runtime.hw.cs.shared_memory_size = 256;
    runtime.hw.cs.workgroup_size = {threads, 1, 1};
    Common::ObjectPool<IR::Inst> pool;
    IR::Block block(pool);
    IR::IREmitter ir(block);
    ir.WriteShared(32, ir.Imm32(1u), ir.Imm32(0u));
    const IR::U32 value{ir.LoadShared(32, false, ir.Imm32(4u))};
    ir.WriteShared(32, value, ir.Imm32(8u));
    ir.Epilogue();
    IR::Program program(info);
    program.blocks.push_back(&block);
    program.post_order_blocks.push_back(&block);
    program.syntax_list.push_back({.data = {.block = &block},
                                   .type = IR::AbstractSyntaxNode::Type::Block});
    program.syntax_list.push_back({.type = IR::AbstractSyntaxNode::Type::Return});
    Profile profile{};
    profile.needs_lds_barriers = true;
    profile.subgroup_size = 32;
    profile.supported_spirv = 0x00010600;
    profile.support_int64 = true;
    Optimization::SharedMemoryBarrierPass(program, runtime, profile);
    const BarrierResult result{Count(block, IR::Opcode::Barrier),
                               Count(block, IR::Opcode::SubgroupBarrier)};
    if (spirv_path) {
        Optimization::CollectShaderInfoPass(program, profile); // declares the LDS types
        Backend::Bindings bindings{};
        const auto code = Backend::SPIRV::EmitSPIRV(profile, runtime, program, bindings);
        std::ofstream out(spirv_path, std::ios::binary);
        out.write(reinterpret_cast<const char*>(code.data()), code.size() * sizeof(u32));
        Check(bool(out) && !code.empty(), "multi-wave compute shader emits SPIR-V");
    }
    return result;
}

static u32 WqmQuadBroadcasts(Gcn::OperandField dst, Gcn::OperandField src) {
    Info info{};
    info.hw_stage = HwStage::Fragment;
    info.sw_stage = SwStage::Fragment;
    RuntimeInfo runtime{};
    runtime.Initialize(HwStage::Fragment, SwStage::Fragment);
    Profile profile{};
    Gcn::Translator translator(info, runtime, profile);
    Gcn::GcnInst inst{};
    inst.opcode = Gcn::Opcode::S_WQM_B64;
    inst.encoding = Gcn::InstEncoding::SOP1;
    inst.category = Gcn::InstCategory::ScalarALU;
    inst.length = 4;
    inst.src_count = 1;
    inst.dst_count = 1;
    inst.src[0].field = src;
    inst.dst[0].field = dst;
    Common::ObjectPool<IR::Inst> pool;
    IR::Block block(pool);
    translator.Translate(&block, 0, IR::Condition::True, std::span<const Gcn::GcnInst>{&inst, 1});
    const u32 broadcasts = Count(block, IR::Opcode::QuadBroadcast);
    if (broadcasts) {
        // One ballot reads the EXEC source (GetSrc64), one builds the quad mask.
        Check(Count(block, IR::Opcode::Ballot) == 2, "s_wqm_b64 ballots the quad mask");
        Check(Count(block, IR::Opcode::SetScc) == 1, "s_wqm_b64 sets SCC");
        Check(Count(block, IR::Opcode::SetVccLo) == 1, "s_wqm_b64 vcc, exec writes VCC");
    }
    return broadcasts;
}

int main(int argc, char** argv) {
    // Exercise the new paths unless the caller chose (no game serial here: the default needs one).
    setenv("TLG_LDS_SMALL", "1", 0);
    setenv("TLG_LDS_MULTI", "1", 0);
    setenv("TLG_LDS_READLANE", "1", 0);
    const bool small = Toggles::SmallGroupLdsBarriers();
    const bool multi = Toggles::MultiWaveLdsBarriers();
    const bool wqm = Toggles::WholeQuadMode();
    std::printf("TLG_LDS_SMALL=%d TLG_LDS_MULTI=%d TLG_WQM=%d\n", small, multi, wqm);

    const BarrierResult wave = RunBarrierPass(64);
    Check(wave.workgroup == 3 && wave.subgroup == 0, "64 threads: workgroup barriers (unchanged)");
    const BarrierResult partial = RunBarrierPass(16);
    Check(partial.workgroup == (small ? 3u : 0u) && partial.subgroup == 0,
          "16 threads: workgroup barriers with TLG_LDS_SMALL");
    std::string spirv;
    if (argc > 1) {
        std::filesystem::create_directories(argv[1]);
        spirv = (std::filesystem::path{argv[1]} / "lds-multi-wave.spv").string();
    }
    const BarrierResult several = RunBarrierPass(256, spirv.empty() ? nullptr : spirv.c_str());
    Check(several.workgroup == 0 && several.subgroup == (multi ? 3u : 0u),
          "256 threads: subgroup barriers with TLG_LDS_MULTI");
    const BarrierResult odd = RunBarrierPass(96);
    Check(odd.workgroup == 0 && odd.subgroup == 0, "96 threads: no barriers");

    Check(WqmQuadBroadcasts(Gcn::OperandField::VccLo, Gcn::OperandField::ExecLo) ==
              (wqm ? 4u : 0u),
          "s_wqm_b64 vcc, exec grows the mask to quads with TLG_WQM");
    Check(WqmQuadBroadcasts(Gcn::OperandField::ExecLo, Gcn::OperandField::ExecLo) == 0,
          "s_wqm_b64 exec, exec stays a no-op");
    Check(Toggles::ShaderBinarySalt() ==
              ((small ? 1u : 0u) | (multi ? 2u : 0u) | (Toggles::LdsUniformReadLane() ? 4u : 0u) |
               (wqm ? 0u : 8u)),
          "shader cache salt follows the switches");
    std::printf("%s\n", failures ? "recompiler fixes: FAILED" : "recompiler fixes: all ok");
    return failures ? 1 : 0;
}
