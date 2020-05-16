import tensorflow as tf

config = tf.ConfigProto()
config.gpu_options.allow_growth = True
sess = tf.Session(config=config)

from encoder.params_model import model_embedding_size as speaker_embedding_size
from utils.argutils import print_args
from synthesizer.inference import Synthesizer
from synthesizer import hparams
from synthesizer.utils import audio
from encoder import inference as encoder
# from vocoder import inference as vocoder
from pathlib import Path
import numpy as np
import librosa
import argparse
import time
import torch
import sys

if __name__ == '__main__':
    ## Info & args
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-e", "--enc_model_fpath", type=Path,
                        default="../models/encoder/saved_models/ge2e_pretrained.pt",
                        help="Path to a saved encoder")
    parser.add_argument("-s", "--syn_model_dir", type=Path,
                        default="../models/synthesizer/saved_models/logs-syne/checkpoints",  # pretrained
                        help="Directory containing the synthesizer model")
    parser.add_argument("-v", "--voc_model_fpath", type=Path,
                        default="../models/vocoder/saved_models/melgan/melgan_multi_speaker.pt",
                        help="Path to a saved vocoder")
    parser.add_argument("-o", "--out_dir", type=Path,
                        default="../data/outs",
                        help="Path to a saved vocoder")
    parser.add_argument("--low_mem", action="store_true", help= \
        "If True, the memory used by the synthesizer will be freed after each use. Adds large "
        "overhead but allows to save some GPU memory for lower-end GPUs.")
    parser.add_argument("--no_sound", action="store_true", help= \
        "If True, audio won't be played.")
    args = parser.parse_args()
    print_args(args, parser)
    if not args.no_sound:
        import sounddevice as sd

    ## Print some environment information (for debugging purposes)
    print("Running a test of your configuration...\n")
    if torch.cuda.is_available():
        device_id = torch.cuda.current_device()
        gpu_properties = torch.cuda.get_device_properties(device_id)
        print("Found %d GPUs available. Using GPU %d (%s) of compute capability %d.%d with "
              "%.1fGb total memory.\n" %
              (torch.cuda.device_count(),
               device_id,
               gpu_properties.name,
               gpu_properties.major,
               gpu_properties.minor,
               gpu_properties.total_memory / 1e9))

    ## Load the models one by one.
    print("Preparing the encoder, the synthesizer and the vocoder...")
    encoder.load_model(args.enc_model_fpath, device='cpu')
    synthesizer = Synthesizer(args.syn_model_dir, low_mem=args.low_mem)
    # vocoder.load_model(args.voc_model_fpath)

    ## Run a test
    print("Testing your configuration with small inputs.")
    print("\tTesting the encoder...")
    encoder.embed_utterance(np.zeros(encoder.sampling_rate))
    embed = np.random.rand(speaker_embedding_size)
    embed /= np.linalg.norm(embed)
    embeds = [embed, np.zeros(speaker_embedding_size)]
    texts = ["你好", "欢迎使用语音克隆工具"]
    print("\tTesting the synthesizer... (loading the model will output a lot of text)")
    mels = synthesizer.synthesize_spectrograms(texts, embeds)

    mel = np.concatenate(mels, axis=1)
    no_action = lambda *args: None
    generated_wav = audio.inv_mel_spectrogram(mel, hparams.hparams)
    print("All test passed! You can now synthesize speech.\n\n")

    print("Interactive generation loop")
    num_generated = 0
    args.out_dir.mkdir(exist_ok=True, parents=True)
    while True:
        try:
            # Get the reference audio filepath
            message = "Reference voice: enter an audio filepath of a voice to be cloned (mp3, " \
                      "wav, m4a, flac, ...):\n"
            in_fpath = Path(input(message).replace("\"", "").replace("\'", ""))
            # - Directly load from the filepath:
            preprocessed_wav = encoder.preprocess_wav(in_fpath)
            print("Loaded file succesfully")

            embed = encoder.embed_utterance(preprocessed_wav)
            print("Created the embedding")

            ## Generating the spectrogram
            text = input("Write a sentence (+-20 words) to be synthesized:\n")

            # The synthesizer works in batch, so you need to put your data in a list or numpy array
            texts = [text]
            embeds = [embed]

            specs = synthesizer.synthesize_spectrograms(texts, embeds)
            spec = specs[0]
            print("Created the mel spectrogram")

            ## Generating the waveform
            print("Synthesizing the waveform:")

            generated_wav = audio.inv_mel_spectrogram(spec, hparams.hparams)

            generated_wav = np.pad(generated_wav, (0, synthesizer.sample_rate), mode="constant")

            # Play the audio (non-blocking)
            if not args.no_sound:
                sd.stop()
                sd.play(generated_wav, synthesizer.sample_rate)
                sd.wait()

            # Save it on the disk
            fpath = args.out_dir.joinpath("demo_output_{}.wav".format(time.strftime('%Y%m%d_%H%M%S')))
            librosa.output.write_wav(fpath, generated_wav.astype(np.float32), synthesizer.sample_rate)
            num_generated += 1
            print("\nSaved output as %s\n\n" % fpath)
        except Exception as e:
            print("Caught exception: %s" % repr(e))
            print("Restarting\n")
