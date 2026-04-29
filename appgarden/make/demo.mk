# demo.mk - High level demonstration workflows

ifndef _DEMO_MK_
_DEMO_MK_ := 1

.PHONY: demo
demo: ## Run end-to-end demo for ai-chatbot-app
	@./scripts/demo-garden.sh ai-chatbot-app

endif # _DEMO_MK_
