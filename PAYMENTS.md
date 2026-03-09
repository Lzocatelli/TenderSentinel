# Pagamentos (Pagar.me)

Pagamento 100% nacional: cartão, boleto e PIX. Checkout hospedado pelo Pagar.me (sem lidar com dados de cartão no seu servidor).

## Variáveis de ambiente

No Railway (ou `.env` local) configure:

| Variável | Descrição |
|----------|-----------|
| `PAGARME_SECRET_KEY` | Chave secreta do Pagar.me (Dashboard → Configurações → Chaves API). Use `sk_test_...` para teste e `sk_...` para produção. |
| `PAGARME_PLAN_ID_BASICO` | ID do plano Básico (ex: `plan_xxxxxxxx`) |
| `PAGARME_PLAN_ID_PROFISSIONAL` | ID do plano Profissional |
| `PAGARME_PLAN_ID_AGENCIA` | ID do plano Agência |

## Configuração no Pagar.me

1. **Criar os planos (assinatura recorrente)**  
   No dashboard Pagar.me (ou via API), crie 3 planos mensais:
   - **Básico** — R$ 99/mês  
   - **Profissional** — R$ 249/mês  
   - **Agência** — R$ 499/mês  

   Cada plano tem um **ID** (formato `plan_xxxxxxxx`). Copie e defina nas variáveis acima.

2. **Webhook**  
   - No Pagar.me: Configurações → Webhooks (ou Integrações).  
   - URL: `https://seu-dominio.up.railway.app/webhook/pagarme`  
   - Eventos recomendados: `subscription.created`, `subscription.updated`, `subscription.canceled` (ou equivalentes da API v5).  

   O webhook ativa o plano no nosso banco quando o pagamento é confirmado e remove o plano quando a assinatura é cancelada.

3. **Ambiente de teste**  
   Use a chave que começa com `sk_test_` e crie planos no ambiente de teste. A URL da API é a mesma (`https://api.pagar.me/core/v5`); a chave define se é teste ou produção.

Sem essas variáveis, a página **Planos** mostra "Em breve" e nenhum link de pagamento é gerado.

## Fluxo

1. Usuário clica em **Assinar** em um plano → o backend gera um **Link de Pagamento** (checkout hospedado) com o plano escolhido e redireciona.  
2. No checkout Pagar.me o cliente paga com cartão, boleto ou PIX.  
3. O Pagar.me envia o webhook para `/webhook/pagarme` → nós atualizamos o plano do cliente (por e-mail ou por `code` = id do nosso usuário).  
4. Cancelamentos feitos no Pagar.me disparam o webhook e o plano é removido aqui.
