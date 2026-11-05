# Configuration

`models.json` maps a model id to its family, parameter count and the OpenAI-compatible endpoint the
runners call. The endpoints are loopback addresses because every model was served locally; change
them to wherever you serve yours. Nothing here downloads weights.

`../prompts/questions.json` holds the generic targeted-question templates and the principle the
multi-verifier arms test. It contains no manuscript text.

See the configuration table in the top-level README for the environment variables the shell drivers
read (`VTB_ROOT`, `VTB_PYTHON`, `VTB_SOURCE_DIR`, `VTB_VLLM_ENV`, `VTB_VLLM_CACHE`, `HF_HOME`).
