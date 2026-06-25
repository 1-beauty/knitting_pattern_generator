"""
knitting/models.py
邻居感知条件编码器（方案B：用attention mask）
"""

import torch
import torch.nn as nn


class NeighborAwareConditioner(nn.Module):
    """
    邻居感知条件编码（方案B）
    
    输入：
      neighbor_ids:  (B, 3, 3) long  - 邻居ID
      neighbor_mask: (B, 3, 3) bool  - True=有效邻居, False=图像外
    
    输出：条件向量 (B, embed_dim)
    
    设计：
    1. num_classes=15（不需要边界标记）
    2. Cross-attention通过key_padding_mask屏蔽无效邻居
    """
    
    def __init__(self, num_classes=15, embed_dim=256, num_heads=8):
        super().__init__()
        self.embed_dim = embed_dim
        
        self.center_embedding   = nn.Embedding(num_classes, embed_dim)
        self.neighbor_embedding = nn.Embedding(num_classes, embed_dim)
        
        # 8个邻居的位置编码
        self.position_embedding = nn.Parameter(
            torch.randn(8, embed_dim) * 0.02
        )
        
        self.neighbor_self_attn = nn.MultiheadAttention(
            embed_dim=embed_dim,
            num_heads=num_heads,
            batch_first=True,
            dropout=0.1,
        )
        self.norm1 = nn.LayerNorm(embed_dim)
        
        self.cross_attention = nn.MultiheadAttention(
            embed_dim=embed_dim,
            num_heads=num_heads,
            batch_first=True,
            dropout=0.1,
        )
        self.norm2 = nn.LayerNorm(embed_dim)
        
        self.fusion = nn.Sequential(
            nn.LayerNorm(embed_dim * 2),
            nn.Linear(embed_dim * 2, embed_dim * 2),
            nn.SiLU(),
            nn.Dropout(0.1),
            nn.Linear(embed_dim * 2, embed_dim),
        )
    
    def forward(self, neighbor_ids, neighbor_mask):
        """
        neighbor_ids:  (B, 3, 3) long
        neighbor_mask: (B, 3, 3) bool
        return: (B, embed_dim)
        """
        center_id = neighbor_ids[:, 1, 1]
        
        # 8个邻居位置（去掉中心[1,1]）
        neighbor_positions = [
            (0, 0), (0, 1), (0, 2),
            (1, 0),         (1, 2),
            (2, 0), (2, 1), (2, 2),
        ]
        
        neighbors = torch.stack([
            neighbor_ids[:, r, c] for r, c in neighbor_positions
        ], dim=1)  # (B, 8)
        
        # 提取8个邻居的mask
        neighbors_mask = torch.stack([
            neighbor_mask[:, r, c] for r, c in neighbor_positions
        ], dim=1)  # (B, 8) bool, True=有效
        
        # 中心特征
        center_feat = self.center_embedding(center_id)  # (B, D)
        
        # 邻居特征 + 位置编码
        neighbor_feat = self.neighbor_embedding(neighbors)  # (B, 8, D)
        neighbor_feat = neighbor_feat + self.position_embedding.unsqueeze(0)
        
        # MultiheadAttention的key_padding_mask约定：
        #   True表示要mask掉（不参与attention）
        #   所以要取反：~neighbors_mask
        attn_padding_mask = ~neighbors_mask  # (B, 8) True=无效要mask
        
        # 邻居self-attention（无效位置不参与）
        # 但要注意：如果某个batch里全是False（不可能，因为至少有有效邻居）
        # 这里假设每个样本至少有1个有效邻居（合理）
        attn_out, _ = self.neighbor_self_attn(
            neighbor_feat, neighbor_feat, neighbor_feat,
            key_padding_mask=attn_padding_mask,
        )
        neighbor_feat = self.norm1(neighbor_feat + attn_out)
        
        # Cross-attention: 中心查询邻居
        query = center_feat.unsqueeze(1)  # (B, 1, D)
        attended, _ = self.cross_attention(
            query, neighbor_feat, neighbor_feat,
            key_padding_mask=attn_padding_mask,
        )
        attended = attended.squeeze(1)
        attended = self.norm2(center_feat + attended)
        
        # 融合
        combined = torch.cat([center_feat, attended], dim=-1)
        cond = self.fusion(combined)
        
        return cond