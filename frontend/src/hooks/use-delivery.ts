import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/services/api/client";
import type {
  DeliveryListResponse,
  DeliveryRetryResponse,
  DeliveryStatsResponse,
} from "@/types/api";

const deliveryQueryKey = ["/admin/delivery"];

// Provides delivery stats behavior; React components use it to access or update application state.
export function useDeliveryStats() {
  return useQuery({
    queryKey: [...deliveryQueryKey, "stats"],
    queryFn: () => apiClient<DeliveryStatsResponse>("/admin/delivery/stats"),
  });
}

// Provides failed deliveries behavior; React components use it to access or update application state.
export function useFailedDeliveries() {
  return useQuery({
    queryKey: [...deliveryQueryKey, "failed"],
    queryFn: () => apiClient<DeliveryListResponse>("/admin/delivery/failed"),
  });
}

// Provides dead lettered deliveries behavior; React components use it to access or update application state.
export function useDeadLetteredDeliveries() {
  return useQuery({
    queryKey: [...deliveryQueryKey, "dead-lettered"],
    queryFn: () => apiClient<DeliveryListResponse>("/admin/delivery/dead-lettered"),
  });
}

// Provides invalidate delivery queries behavior; React components use it to access or update application state.
function useInvalidateDeliveryQueries() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: deliveryQueryKey });
}

// Provides retry delivery behavior; React components use it to access or update application state.
export function useRetryDelivery() {
  const invalidateDeliveryQueries = useInvalidateDeliveryQueries();
  return useMutation({
    mutationFn: (outboxId: string) =>
      apiClient<DeliveryRetryResponse>(`/admin/delivery/${outboxId}/retry`, {
        method: "POST",
      }),
    onSuccess: invalidateDeliveryQueries,
  });
}

// Provides retry all deliveries behavior; React components use it to access or update application state.
export function useRetryAllDeliveries() {
  const invalidateDeliveryQueries = useInvalidateDeliveryQueries();
  return useMutation({
    mutationFn: () =>
      apiClient<DeliveryRetryResponse>("/admin/delivery/retry-all", {
        method: "POST",
      }),
    onSuccess: invalidateDeliveryQueries,
  });
}
