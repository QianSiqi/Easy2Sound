# Makefile for Easy2Sound Rust components
# Builds arpabet, ch-ddy-ysq, ipa-ysq-pack, jp-ddy-ysq, resampler_cilent
# Output binaries are placed in Main-Run/

CARGO   = cargo
RM      = rm -f
COPY    = cp -f
TARGET  = target/release
OUTDIR  = .

# Binary names (derived from each Cargo.toml's [package].name)
BIN_ARPABET      = english_dict_lookup.exe
BIN_CH_DDY       = ch-ddy-ysq.exe
BIN_IPA          = ipa-ysq.exe
BIN_JP_DDY       = jp-ddy-ysq.exe
BIN_RESAMPLER    = resampler.exe

# Project directories
DIR_ARPABET      = arpabet
DIR_CH_DDY       = ch-ddy-ysq
DIR_IPA          = ipa-ysq-pack
DIR_JP_DDY       = jp-ddy-ysq
DIR_RESAMPLER    = resampler_cilent
DIR_PYCACHE      = _pycache_

.PHONY: all clean arpabet ch-ddy ipa jp-ddy resampler

all: arpabet ch-ddy ipa jp-ddy resampler

arpabet:
	cd $(DIR_ARPABET) && $(CARGO) build --release
	$(COPY) $(DIR_ARPABET)/$(TARGET)/$(BIN_ARPABET) $(OUTDIR)/

ch-ddy:
	cd $(DIR_CH_DDY) && $(CARGO) build --release
	$(COPY) $(DIR_CH_DDY)/$(TARGET)/$(BIN_CH_DDY) $(OUTDIR)/

ipa:
	cd $(DIR_IPA) && $(CARGO) build --release
	$(COPY) $(DIR_IPA)/$(TARGET)/$(BIN_IPA) $(OUTDIR)/

jp-ddy:
	cd $(DIR_JP_DDY) && $(CARGO) build --release
	$(COPY) $(DIR_JP_DDY)/$(TARGET)/$(BIN_JP_DDY) $(OUTDIR)/

resampler:
	cd $(DIR_RESAMPLER) && $(CARGO) build --release
	$(COPY) $(DIR_RESAMPLER)/$(TARGET)/$(BIN_RESAMPLER) $(OUTDIR)/

clean:
	cd $(DIR_ARPABET) && $(CARGO) clean
	cd $(DIR_CH_DDY) && $(CARGO) clean
	cd $(DIR_IPA) && $(CARGO) clean
	cd $(DIR_JP_DDY) && $(CARGO) clean
	cd $(DIR_RESAMPLER) && $(CARGO) clean
	-$(RM) $(OUTDIR)/$(BIN_ARPABET)
	-$(RM) $(OUTDIR)/$(BIN_CH_DDY)
	-$(RM) $(OUTDIR)/$(BIN_IPA)
	-$(RM) $(OUTDIR)/$(BIN_JP_DDY)
	-$(RM) $(OUTDIR)/$(BIN_RESAMPLER)
	-$(RM) $(OUTDIR)/$(DIR_PYCACHE)
