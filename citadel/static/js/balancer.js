;(function($){

$('a[name=delete-route]').click(function(e){
  e.preventDefault();
  if (!confirm('确认删除?')) {
    return;
  }
  var self = $(this);
  var url = '/ajax/loadbalance/route/{id}/remove'.replace('{id}', self.data('id'));
  $.post(url, {}, function(){
    self.parent().parent().remove();
  });
});

$('select[name=appname]').change(function(){
  var appname = $(this).val();
  var url = '/ajax/app/{appname}/online-entrypoints'.replace('{appname}', appname);
  var podUrl = '/ajax/app/{appname}/online-pods'.replace('{appname}', appname);

  $.get(url, {}, function(r){
    var ep = $('select[name=entrypoint]').html('');
    $.each(r, function(index, data){
      ep.append($('<option>').val(data).text(data));
    })
    ep.append($('<option>').val('_all').text('_all'));
  });
  $.get(podUrl, {}, function(r){
    var ep = $('select[name=podname]').html('');
    $.each(r, function(index, data){
      ep.append($('<option>').val(data).text(data));
    })
  });
});

$('#refresh-btn').click(function(){
  var name = $(this).data('name');
  var url = '/ajax/loadbalance/{name}/refresh'.replace('{name}', name);
  if (!confirm('确定要刷新记录么?')) {
    return;
  }
  if (!confirm('还是再问一次吧')) {
    return;
  }
  $.post(url, {}, function(r){
    window.location.reload();
  });
});

})(jQuery);
