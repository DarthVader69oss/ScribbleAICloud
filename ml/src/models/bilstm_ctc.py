"""
src/models/bilstm_ctc.py

3 x bidirectional LSTM (256 units per direction, dropout 0.3) -> linear -> log-softmax
over (characters + CTC blank). Packed sequences so padding never reaches the LSTM.
Output shape (T, B, C), which is what nn.CTCLoss expects.
"""
import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence


class BiLSTMCTC(nn.Module):
    def __init__(self, input_dim, num_classes, hidden_size=256, num_layers=3,
                 dropout=0.3, bidirectional=True, pack_sequences=True):
        super().__init__()
        self.pack_sequences = pack_sequences
        self.lstm = nn.LSTM(input_dim, hidden_size, num_layers=num_layers, batch_first=True,
                            dropout=dropout if num_layers > 1 else 0.0, bidirectional=bidirectional)
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size * (2 if bidirectional else 1), num_classes)
        self.num_classes = num_classes

    @classmethod
    def from_config(cls, cfg, num_classes):
        m = cfg["model"]
        return cls(cfg["features"]["input_dim"], num_classes, m["hidden_size"], m["num_layers"],
                   m["dropout"], m["bidirectional"], m.get("pack_sequences", True))

    def forward(self, x, lengths):
        """x: (B, T, F) padded; lengths: (B,) true lengths. Returns log_probs (T, B, C), lengths."""
        if bool((lengths == x.shape[1]).all()) or not self.pack_sequences:
            # no padding (e.g. batch of one in the demo): plain call, identical result, much faster on CPU
            out, _ = self.lstm(x)
            out_len = lengths.cpu()
        else:
            packed = pack_padded_sequence(x, lengths.cpu(), batch_first=True, enforce_sorted=False)
            out, _ = self.lstm(packed)
            out, out_len = pad_packed_sequence(out, batch_first=True, total_length=x.shape[1])
        logits = self.fc(self.dropout(out))                 # (B, T, C)
        return logits.log_softmax(-1).transpose(0, 1), out_len

    def num_parameters(self):
        return sum(p.numel() for p in self.parameters())
