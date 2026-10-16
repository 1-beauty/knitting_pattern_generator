# -*- coding: utf-8 -*-
"""P3-a 参考文献转 Elsevier numbered 风格(去 [J]/[C]// 等 GB/T 标识) + 悬挂缩进；
P3-b 图1 图注 4.5 节 -> 4.6 节。"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document
from docx.shared import Twips
MAIN = r'e:\DeskTop\knitting_pattern_generator\docs\论文to_cii.docx'

REFS = {
1: 'Shima Seiki, SDS-ONE APEX Series: All-in-One Design System for Computerized Flat Knitting, https://www.shimaseiki.com/product/design, 2026 (accessed 29 July 2026).',
2: 'STOLL by KARL MAYER, M1plus Pattern Software for Computerized Flat Knitting Machines, https://www.stoll.com/en/, 2026 (accessed 29 July 2026).',
3: 'T.C. Yu, J. McCann, Coupling programs and visualization for machine knitting, in: Proc. 5th Annu. ACM Symp. on Computational Fabrication (SCF \'20), ACM, 2020. doi:10.1145/3424630.3425410.',
4: 'V. Narayanan, K. Wu, C. Yuksel, J. McCann, Visual knitting machine programming, ACM Trans. Graph. 38 (4) (2019) 1-13. doi:10.1145/3306346.3322995.',
5: 'L. Schaerf, A. Alfarano, E. Postma, ColorwAI: Generative colorways of textiles through GAN and diffusion disentanglement, arXiv:2407.11514 (2024).',
6: 'C. Zhang, Y. Wang, F.V. Carrasco, et al., FabricDiffusion: High-fidelity texture transfer for 3D garments generation from in-the-wild clothing images, in: SIGGRAPH Asia 2024 Conf. Papers, ACM, 2024.',
7: 'Y. Sun, Z. Hao, et al., Deep learning for 3D garment generation: A review, Text. Res. J. (2025). doi:10.1177/00405175251335188.',
8: 'X. Li, Y. Sun, Z. Sha, LLM4CAD: Multi-modal large language models for 3D computer-aided design generation, in: Proc. ASME 2024 Int. Des. Eng. Tech. Conf., 2024.',
9: 'P. Schneider, M. Klettner, K. Jokinen, et al., Evaluating large language models in semantic parsing for conversational question answering over knowledge graphs, in: Proc. 16th Int. Conf. on Agents and Artificial Intelligence (ICAART), SciTePress, 2024.',
10: 'B. Wang, Z. Wang, X. Wang, et al., Grammar prompting for domain-specific language generation with large language models, in: Adv. Neural Inf. Process. Syst., 2023.',
11: 'T. Scholak, N. Schucher, D. Bahdanau, PICARD: Parsing incrementally for constrained auto-regressive decoding from language models, in: Proc. 2021 Conf. on Empirical Methods in Natural Language Processing, 2021, pp. 9895-9901.',
12: 'D.J. Spencer, Knitting Technology: A Comprehensive Handbook and Practical Guide, 3rd ed., Woodhead Publishing, Cambridge, 2001.',
13: 'X. Liu, Knit-FLUX: Simulation of knitted fabric images based on low-rank adaptation of diffusion models, Appl. Sci. 15 (16) (2025) 8999.',
14: 'S. Zhu, L. Li, KnitDiff: Constraint-aware diffusion modeling for knit pattern generation, Text. Res. J. (2025). doi:10.1177/00405175251397601.',
15: 'A. Kaspar, T.H. Oh, L. Makatura, et al., Neural inverse knitting: From images to manufacturing instructions, in: Proc. 36th Int. Conf. on Machine Learning, PMLR, 2019, pp. 3272-3281.',
16: 'T. Brooks, A. Holynski, A.A. Efros, InstructPix2Pix: Learning to follow image editing instructions, in: Proc. IEEE/CVF Conf. on Computer Vision and Pattern Recognition, 2023, pp. 18392-18402.',
17: 'A. Daareyni, A. Martikkala, H. Mokhtarian, et al., Generative AI meets CAD: Enhancing engineering design to manufacturing processes with large language models, Int. J. Adv. Manuf. Technol. (2025). doi:10.1007/s00170-025-15830-2.',
18: 'W. Feng, W. Zhu, T. Fu, et al., LayoutGPT: Compositional visual planning and generation with large language models, in: Adv. Neural Inf. Process. Syst., 2023.',
19: 'M.S. Khan, S. Sinha, T.U. Sheikh, et al., Text2CAD: Generating sequential CAD models from beginner-to-expert level text prompts, in: Adv. Neural Inf. Process. Syst., 2024.',
20: 'C. Si, Y. Zhang, R. Li, et al., Design2Code: Benchmarking multimodal code generation for automated front-end engineering, in: Proc. 2025 Conf. of the Nations of the Americas Chapter of the ACL: Human Language Technologies, 2025, pp. 3956-3974.',
21: 'J. Ho, A. Jain, P. Abbeel, Denoising diffusion probabilistic models, in: Adv. Neural Inf. Process. Syst., 2020, pp. 6840-6851.',
22: 'R. Rombach, A. Blattmann, D. Lorenz, et al., High-resolution image synthesis with latent diffusion models, in: Proc. IEEE/CVF Conf. on Computer Vision and Pattern Recognition, 2022, pp. 10684-10695.',
23: 'L. Zhang, A. Rao, M. Agrawala, Adding conditional control to text-to-image diffusion models, in: Proc. IEEE/CVF Int. Conf. on Computer Vision, 2023, pp. 3836-3847.',
24: 'W. Peebles, S. Xie, Scalable diffusion models with transformers, in: Proc. IEEE/CVF Int. Conf. on Computer Vision, 2023, pp. 4195-4205.',
25: 'F. Scheidt, J. Ou, H. Ishii, et al., deepKnit: Learning-based generation of machine knitting code, Procedia Manuf. 51 (2020) 485-492.',
26: 'V. Narayanan, L. Albaugh, J. Hodgins, et al., Automatic machine knitting of 3D meshes, ACM Trans. Graph. 37 (3) (2018) 35:1-35:15.',
27: 'A. Kaspar, K. Wu, Y. Luo, et al., Knit sketching: From cut & sew patterns to machine-knit garments, ACM Trans. Graph. 40 (4) (2021) 1-15.',
28: 'A. Kaspar, L. Makatura, W. Matusik, Knitting skeletons: A computer-aided design tool for shaping and patterning of knitted garments, in: Proc. 32nd Annu. ACM Symp. on User Interface Software and Technology, 2019, pp. 53-65.',
29: 'L. Kapllani, C. Amanatides, G. Dion, et al., TopoKnit: A process-oriented representation for modeling the topology of yarns in weft-knitted textiles, Graph. Models 118 (2021) 101114.',
30: 'V. Narayanan, K. Wu, C. Yuksel, et al., Visual knitting machine programming, ACM Trans. Graph. 38 (4) (2019) 63:1-63:13.',
31: 'A. Karmon, Y. Sterman, KNITIT: A computational tool for design, simulation, and fabrication of multiple structured knits, in: Proc. 12th Int. Conf. on Tangible, Embedded, and Embodied Interaction, ACM, 2018.',
32: 'J. McCann, L. Albaugh, V. Narayanan, et al., A compiler for 3D machine knitting, ACM Trans. Graph. 35 (4) (2016) 49:1-49:11.',
33: 'J. Lin, V. Narayanan, Y. Ikarashi, et al., Semantics and scheduling for machine knitting compilers, ACM Trans. Graph. 42 (4) (2023). doi:10.1145/3592449.',
34: 'Y. Hirose, M. Larsson, T. Igarashi, skCAD: A design tool for solid knitting with automatic pattern generation, in: Proc. 2026 CHI Conf. on Human Factors in Computing Systems, ACM, 2026. doi:10.1145/3772318.3791148.',
35: 'M. Hofmann, J. Mankoff, S.E. Hudson, KnitGIST: A programming synthesis toolkit for generating functional machine-knitting textures, in: Proc. 33rd Annu. ACM Symp. on User Interface Software and Technology, ACM, 2020, pp. 1234-1247.',
36: 'L. Regenwetter, A.H. Nobari, F. Ahmed, Deep generative models in engineering design: A review, J. Mech. Des. 144 (7) (2022) 071704.',
37: 'L. Sun, W. Shi, C. Xuan, et al., Research on scheduling algorithm of knitting production workshop based on deep reinforcement learning, Machines 12 (8) (2024) 579.',
38: 'T. Koo, F. Liu, L. He, Automata-based constraints for language model decoding, in: First Conf. on Language Modeling, 2024.',
39: 'F. Rossi, P. Van Beek, T. Walsh, Handbook of Constraint Programming, Elsevier, Amsterdam, 2006.',
40: 'L. Perron, V. Furnon, OR-Tools: Software suite for combinatorial optimization, https://developers.google.com/optimization, 2026 (accessed 20 September 2026).',
41: 'J.M. Kaldor, D.L. James, S. Marschner, Simulating knitted cloth at the yarn level, ACM Trans. Graph. 27 (3) (2008) 65:1-65:9.',
42: 'O. Ronneberger, P. Fischer, T. Brox, U-Net: Convolutional networks for biomedical image segmentation, in: Medical Image Computing and Computer-Assisted Intervention (MICCAI), 2015, pp. 234-241.',
43: 'Y. Lipman, R.T.Q. Chen, H. Ben-Hamu, et al., Flow matching for generative modeling, in: Int. Conf. on Learning Representations, 2023.',
44: 'X. Liu, C. Gong, Q. Liu, Flow straight and fast: Learning to generate and transfer data with rectified flow, in: Int. Conf. on Learning Representations, 2023.',
45: 'Z. Wang, A.C. Bovik, H.R. Sheikh, et al., Image quality assessment: From error visibility to structural similarity, IEEE Trans. Image Process. 13 (4) (2004) 600-612.',
46: 'R. Zhang, P. Isola, A.A. Efros, et al., The unreasonable effectiveness of deep features as a perceptual metric, in: Proc. IEEE Conf. on Computer Vision and Pattern Recognition, 2018, pp. 586-595.',
47: 'DeepSeek-AI, A. Liu, B. Feng, et al., DeepSeek-V3 technical report, arXiv:2412.19437 (2024).',
48: 'H. Twigg-Smith, E. Whiting, N. Peek, KnitScape: Computational design and yarn-level simulation of slip and tuck colorwork knitting patterns, in: Proc. 2024 CHI Conf. on Human Factors in Computing Systems, ACM, 2024. doi:10.1145/3613904.3642799.',
49: 'A. Kaspar, J. McCann, W. Matusik, Knitout: A machine-independent representation for machine knitting, https://textiles-lab.github.io/knitout/, 2026 (accessed 29 July 2026).',
}

doc = Document(MAIN)
n = 0
for p in doc.paragraphs:
    m = re.match(r'^\[(\d+)\]\s*', p.text.strip())
    if not m:
        continue
    k = int(m.group(1))
    if k not in REFS:
        continue
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    p.add_run(f'[{k}] ' + REFS[k])
    pf = p.paragraph_format
    pf.left_indent = Twips(480)
    pf.first_line_indent = Twips(-480)  # 悬挂缩进
    n += 1
print('refs reformatted:', n)

# P3-b: 图1 图注 4.5 节 -> 4.6 节
fixed = 0
for p in doc.paragraphs:
    if p.text.strip().startswith('图 1 ') and '4.5 节' in p.text:
        for r in p.runs:
            if '4.5 节' in r.text:
                r.text = r.text.replace('4.5 节', '4.6 节'); fixed += 1
print('fig1 caption 4.5->4.6 fixed runs:', fixed)
doc.save(MAIN)
print('saved')
