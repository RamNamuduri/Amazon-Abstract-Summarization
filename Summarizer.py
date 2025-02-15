In [1]:
 
import torch
import torch.nn as nn
import torch
from torchtext.data.utils import get_tokenizer
from torch.utils.data import DataLoader
from collections import Counter
from torchtext.vocab import Vocab
from torch.nn.utils.rnn import pad_sequence
import math
import torchtext
from torchtext.utils import download_from_url, extract_archive
from torch import Tensor
import time
from torch.nn import (TransformerEncoder, TransformerDecoder,
                      TransformerEncoderLayer, TransformerDecoderLayer)
import numpy as np


In [2]:
  
#Amazon Dataset from HuggingFace
!pip install datasets
from datasets import load_dataset
train_data = load_dataset(
   'amazon_reviews_multi', 'en',split='train')
test_data = load_dataset(
   'amazon_reviews_multi', 'en',split='test')
validation_data = load_dataset(
   'amazon_reviews_multi', 'en',split='validation')


In [3]:

#Selecting subset of the dataset
def get_rand_int_arr(numVals, maxVal):
    random = np.random.choice(np.arange(0, maxVal), replace=False, size=(numVals))
    random = torch.tensor(random)
    return random

TRAIN_DATA_SIZE = 30000
VALID_DATA_SIZE = 4000
TRAIN_MAXVAL = 199998
VALID_MAXVAL = 4999
train_data = train_data.select(get_rand_int_arr(TRAIN_DATA_SIZE,TRAIN_MAXVAL))
valid_data = validation_data.select(get_rand_int_arr(VALID_DATA_SIZE,VALID_MAXVAL))


In [4]:

  #Creating & saving the vocabulary - word : frequency
en_tokenizer = get_tokenizer('spacy', language='en_core_web_sm')

counter = Counter()
for line in train_data['review_body'][0:TRAIN_DATA_SIZE]:
        counter.update(en_tokenizer(line))
for line in train_data['review_title'][0:TRAIN_DATA_SIZE]:
        counter.update(en_tokenizer(line))

vocab = Vocab(counter, specials=['<unk>', '<pad>', '<bos>', '<eos>'])


def save_vocab(vocab, path):
    import pickle
    pfile = open(path, 'wb')
    pickle.dump(vocab, pfile)
    pfile.close()

save_vocab(vocab, "vocab.pt")

#tokenizing dataset using vocabulary
def data_process(dataset):
    review_body_iter = dataset['review_body']
    review_title_iter = dataset['review_title']
    data = []
    for (review_body, review_title) in zip(review_body_iter, review_title_iter):
        review_body_tensor = torch.tensor([vocab[token] for token in en_tokenizer(review_body.rstrip("\n"))], dtype=torch.long)
        review_title_tensor = torch.tensor([vocab[token] for token in en_tokenizer(review_title.rstrip("\n"))], dtype=torch.long)
        data.append((review_body_tensor, review_title_tensor))
    return data

train_data_tensors = data_process(train_data)
valid_data_tensors = data_process(valid_data)

BATCH_SIZE = 50
PAD_IDX = vocab['<pad>']
BOS_IDX = vocab['<bos>']
EOS_IDX = vocab['<eos>']

def generate_batch(data_batch):
  body_batch, title_batch = [], []
  for (body_item, title_item) in data_batch:
    body_batch.append(torch.cat([torch.tensor([BOS_IDX]), body_item, torch.tensor([EOS_IDX])], dim=0))
    title_batch.append(torch.cat([torch.tensor([BOS_IDX]), title_item, torch.tensor([EOS_IDX])], dim=0))
  body_batch = pad_sequence(body_batch, padding_value=PAD_IDX)
  title_batch = pad_sequence(title_batch, padding_value=PAD_IDX)
  print(title_batch.size())
  return body_batch, title_batch

train_iter = DataLoader(train_data_tensors, batch_size=BATCH_SIZE,
                        shuffle=True, collate_fn=generate_batch)
valid_iter = DataLoader(valid_data_tensors, batch_size=BATCH_SIZE,
                        shuffle=True, collate_fn=generate_batch)


In [5]:
  
class PositionalEncoding(nn.Module):
    def __init__(self, emb_size: int, dropout, maxlen: int = 5000):
        super(PositionalEncoding, self).__init__()
        den = torch.exp(- torch.arange(0, emb_size, 2) * math.log(10000) / emb_size)
        pos = torch.arange(0, maxlen).reshape(maxlen, 1)
        pos_embedding = torch.zeros((maxlen, emb_size))
        pos_embedding[:, 0::2] = torch.sin(pos * den)
        pos_embedding[:, 1::2] = torch.cos(pos * den)
        pos_embedding = pos_embedding.unsqueeze(-2)

        self.dropout = nn.Dropout(dropout)
        self.register_buffer('pos_embedding', pos_embedding)

    def forward(self, token_embedding: Tensor):
        return self.dropout(token_embedding +
                            self.pos_embedding[:token_embedding.size(0),:])
    
class TokenEmbedding(nn.Module):
    def __init__(self, vocab_size: int, emb_size):
        super(TokenEmbedding, self).__init__()
        self.embedding = nn.Embedding(vocab_size, emb_size)
        self.emb_size = emb_size
    def forward(self, tokens: Tensor):
        return self.embedding(tokens.long()) * math.sqrt(self.emb_size)
      
      
In [6]:

class Seq2SeqTransformer(nn.Module):
    def __init__(self, num_encoder_layers: int, num_decoder_layers: int,
                 emb_size: int, src_vocab_size: int, tgt_vocab_size: int,
                 dim_feedforward:int = 512, dropout:float = 0.1):
        super(Seq2SeqTransformer, self).__init__()
        encoder_layer = TransformerEncoderLayer(d_model=emb_size, nhead=NHEAD,
                                                dim_feedforward=dim_feedforward)
        self.transformer_encoder = TransformerEncoder(encoder_layer, num_layers=num_encoder_layers)
        decoder_layer = TransformerDecoderLayer(d_model=emb_size, nhead=NHEAD,
                                                dim_feedforward=dim_feedforward)
        self.transformer_decoder = TransformerDecoder(decoder_layer, num_layers=num_decoder_layers)

        self.generator = nn.Linear(emb_size, tgt_vocab_size)
        self.src_tok_emb = TokenEmbedding(src_vocab_size, emb_size)
        self.tgt_tok_emb = TokenEmbedding(tgt_vocab_size, emb_size)
        self.positional_encoding = PositionalEncoding(emb_size, dropout=dropout)

    def forward(self, src: Tensor, trg: Tensor, src_mask: Tensor,
                tgt_mask: Tensor, src_padding_mask: Tensor,
                tgt_padding_mask: Tensor, memory_key_padding_mask: Tensor):
        src_emb = self.positional_encoding(self.src_tok_emb(src))
        tgt_emb = self.positional_encoding(self.tgt_tok_emb(trg))
        memory = self.transformer_encoder(src_emb, src_mask, src_padding_mask)
        outs = self.transformer_decoder(tgt_emb, memory, tgt_mask, None,
                                        tgt_padding_mask, memory_key_padding_mask)
        return self.generator(outs)

    def encode(self, src: Tensor, src_mask: Tensor):
        return self.transformer_encoder(self.positional_encoding(
                            self.src_tok_emb(src)), src_mask)

    def decode(self, tgt: Tensor, memory: Tensor, tgt_mask: Tensor):
        return self.transformer_decoder(self.positional_encoding(
                          self.tgt_tok_emb(tgt)), memory,
                          tgt_mask)


In [7]:

def generate_square_subsequent_mask(sz):
    mask = (torch.triu(torch.ones((sz, sz), device=DEVICE)) == 1).transpose(0, 1)
    mask = mask.float().masked_fill(mask == 0, float('-inf')).masked_fill(mask == 1, float(0.0))
    return mask

def create_mask(src, tgt):
  src_seq_len = src.shape[0]
  tgt_seq_len = tgt.shape[0]

  tgt_mask = generate_square_subsequent_mask(tgt_seq_len)
  src_mask = torch.zeros((src_seq_len, src_seq_len), device=DEVICE).type(torch.bool)

  src_padding_mask = (src == PAD_IDX).transpose(0, 1)
  tgt_padding_mask = (tgt == PAD_IDX).transpose(0, 1)
  return src_mask, tgt_mask, src_padding_mask, tgt_padding_mask


In [8]:

VOCAB_SIZE = len(vocab)
EMB_SIZE = 512
NHEAD = 8
FFN_HID_DIM = 512
NUM_ENCODER_LAYERS = 4
NUM_DECODER_LAYERS = 4
NUM_EPOCHS = 3

DEVICE = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

transformer = Seq2SeqTransformer(NUM_ENCODER_LAYERS, NUM_DECODER_LAYERS,
                                 EMB_SIZE, VOCAB_SIZE, VOCAB_SIZE,
                                 FFN_HID_DIM)

for p in transformer.parameters():
    if p.dim() > 1:
        nn.init.xavier_uniform_(p)

transformer = transformer.to(DEVICE)

loss_fn = torch.nn.CrossEntropyLoss(ignore_index=PAD_IDX)

optimizer = torch.optim.Adam(
    transformer.parameters(), lr=0.0001, betas=(0.9, 0.98), eps=1e-9
    
)

def train_epoch(model, train_iter, optimizer):
  model.train()
  losses = 0
  for idx, (src, tgt) in enumerate(train_iter):
      src = src.to(DEVICE)
      tgt = tgt.to(DEVICE)

      tgt_input = tgt[:-1, :]

      src_mask, tgt_mask, src_padding_mask, tgt_padding_mask = create_mask(src, tgt_input)

      logits = model(src, tgt_input, src_mask, tgt_mask,
                                src_padding_mask, tgt_padding_mask, src_padding_mask)

      optimizer.zero_grad()

      tgt_out = tgt[1:,:]
      loss = loss_fn(logits.reshape(-1, logits.shape[-1]), tgt_out.reshape(-1))
      loss.backward()

      optimizer.step()
      losses += loss.item()
  return losses / len(train_iter)


def evaluate(model, val_iter):
  model.eval()
  losses = 0
  for idx, (src, tgt) in (enumerate(valid_iter)):
    print((f"\rVal Iter {idx} of {len(val_iter)}"), end='', flush=True )
    src = src.to(DEVICE)
    tgt = tgt.to(DEVICE)

    tgt_input = tgt[:-1, :]

    src_mask, tgt_mask, src_padding_mask, tgt_padding_mask = create_mask(src, tgt_input)

    logits = model(src, tgt_input, src_mask, tgt_mask,
                              src_padding_mask, tgt_padding_mask, src_padding_mask)
    tgt_out = tgt[1:,:]
    loss = loss_fn(logits.reshape(-1, logits.shape[-1]), tgt_out.reshape(-1))
    losses += loss.item()
  return losses / len(val_iter)


In [9]:
  
print("Training Starts")
for epoch in range(1, NUM_EPOCHS+1):
  start_time = time.time()
  train_loss = train_epoch(transformer, train_iter, optimizer)
  end_time = time.time()
  val_loss = evaluate(transformer, valid_iter)
  print((f"Epoch: {epoch}, Train loss: {train_loss:.3f}, Val loss: {val_loss:.3f}, "
          f"Epoch time = {(end_time - start_time):.3f}s"))

PATH = "train.pt"
torch.save(transformer.state_dict(), PATH)
print("Model state saved")


In [10]:
  
VOCAB_SIZE = len(vocab)
EMB_SIZE = 512
NHEAD = 8
FFN_HID_DIM = 512
NUM_ENCODER_LAYERS = 4
NUM_DECODER_LAYERS = 4
NUM_EPOCHS = 3

DEVICE = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

transformer = Seq2SeqTransformer(NUM_ENCODER_LAYERS, NUM_DECODER_LAYERS,
                                 EMB_SIZE, VOCAB_SIZE, VOCAB_SIZE,
                                 FFN_HID_DIM)

for p in transformer.parameters():
    if p.dim() > 1:
        nn.init.xavier_uniform_(p)

transformer = transformer.to(DEVICE)

loss_fn = torch.nn.CrossEntropyLoss(ignore_index=PAD_IDX)

optimizer = torch.optim.Adam(
    transformer.parameters(), lr=0.0001, betas=(0.9, 0.98), eps=1e-9
    
)


def greedy_decode(model, src, src_mask, max_len, start_symbol):
    src = src.to(DEVICE)
    src_mask = src_mask.to(DEVICE)

    memory = model.encode(src, src_mask)
    print(memory.size)
    ys = torch.ones(1, 1).fill_(start_symbol).type(torch.long).to(DEVICE)
    for i in range(max_len-1):
        memory = memory.to(DEVICE)
        memory_mask = torch.zeros(ys.shape[0], memory.shape[0]).to(DEVICE).type(torch.bool)
        tgt_mask = (generate_square_subsequent_mask(ys.size(0))
                                    .type(torch.bool)).to(DEVICE)
        out = model.decode(ys, memory, tgt_mask)
        out = out.transpose(0, 1)
        prob = model.generator(out[:, -1])*-1
        _, next_word = torch.max(prob, dim = 1)
        next_word = next_word.item()
        
        ys = torch.cat([ys,
                        torch.ones(1, 1).type_as(src.data).fill_(next_word)], dim=0)
        if next_word == EOS_IDX:
          break
    return ys


def translate(model, src, src_vocab, tgt_vocab, src_tokenizer):
  model.eval()
  tokens = [BOS_IDX] + [src_vocab.stoi[tok] for tok in src_tokenizer(src)]+ [EOS_IDX]
  num_tokens = len(tokens)
  src = (torch.LongTensor(tokens).reshape(num_tokens, 1) )
  src_mask = (torch.zeros(num_tokens, num_tokens)).type(torch.bool)
  tgt_tokens = greedy_decode(model,  src, src_mask, max_len=num_tokens+5, start_symbol=BOS_IDX).flatten()
  return " ".join([tgt_vocab.itos[tok] for tok in tgt_tokens]).replace("<bos>", "").replace("<eos>", "")


PATH = "train.pt"
print("Eval begin")
device = torch.device('cpu')
transformer.load_state_dict(torch.load(PATH, map_location=device))
print("Model load complete")
test_review = "On first use it didn’t heat up and now it doesn’t work at all."
print(translate(transformer, test_review, vocab, vocab, en_tokenizer))


In [11]:
#Compare the results from the T5 model to the results above
#T5 model HuggingFace's fine-tuned abstractive summarization
!pip install transformers
from transformers import pipeline
summarizer = pipeline('summarization')
sentence = "On first use it didn’t heat up and now it doesn’t work at all."
print(summarizer(sentence,  do_sample=False))


In [12]:
  
#Amazon Reviews Multi Dataset citation
@inproceedings{marc_reviews,
    title={The Multilingual Amazon Reviews Corpus},
    author={Keung, Phillip and Lu, Yichao and Szarvas, György and Smith, Noah A.},
    booktitle={Proceedings of the 2020 Conference on Empirical Methods in Natural Language Processing},
    year={2020}
}
