import torch
ckpt = torch.load('/data/wr/knitting_pattern_generator/conditional-flow-matching-main/checkpoints/stage2/best.pt', map_location='cpu', weights_only=False)
print('Keys:', list(ckpt.keys()))
print('patch_size:', ckpt.get('patch_size', 'NOT FOUND'))
